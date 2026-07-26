use anchor_lang::prelude::*;
use anchor_spl::token_interface::{self, Mint, TokenAccount, TokenInterface, TransferChecked};

declare_id!("GN2d9tgQvwWqFaGuVomqBxcngW8c3CPWe4JRG6bP4rD");

const SECONDS_PER_DAY: i64 = 86_400;
const MAX_ASSET_POLICY_LIFETIME_SECONDS: i64 = 900;

#[program]
pub mod iat_checkout {
    use super::*;

    pub fn initialize_config(
        ctx: Context<InitializeConfig>,
        quote_authority: Pubkey,
        max_order_iat: u64,
        wallet_daily_iat_cap: u64,
        treasury_daily_iat_cap: u64,
    ) -> Result<()> {
        require!(max_order_iat > 0, CheckoutError::InvalidLimit);
        require!(
            quote_authority != Pubkey::default(),
            CheckoutError::InvalidAuthority
        );
        require!(
            wallet_daily_iat_cap >= max_order_iat,
            CheckoutError::InvalidLimit
        );
        require!(
            treasury_daily_iat_cap >= wallet_daily_iat_cap,
            CheckoutError::InvalidLimit
        );
        require_keys_neq!(
            ctx.accounts.iat_mint.key(),
            ctx.accounts.settlement_escrow.key(),
            CheckoutError::DuplicateAccount
        );
        require_keys_eq!(
            ctx.accounts.settlement_escrow.mint,
            ctx.accounts.iat_mint.key(),
            CheckoutError::InvalidSettlementEscrow
        );

        let config = &mut ctx.accounts.config;
        config.authority = ctx.accounts.authority.key();
        config.pending_authority = Pubkey::default();
        config.quote_authority = quote_authority;
        config.iat_mint = ctx.accounts.iat_mint.key();
        config.treasury_iat_vault = ctx.accounts.treasury_iat_vault.key();
        config.settlement_escrow = ctx.accounts.settlement_escrow.key();
        config.max_order_iat = max_order_iat;
        config.wallet_daily_iat_cap = wallet_daily_iat_cap;
        config.treasury_daily_iat_cap = treasury_daily_iat_cap;
        config.treasury_usage_day = 0;
        config.treasury_usage_iat = 0;
        config.paused = true;
        config.bump = ctx.bumps.config;
        config.vault_authority_bump = ctx.bumps.vault_authority;
        Ok(())
    }

    pub fn configure_asset(
        ctx: Context<ConfigureAsset>,
        ratio_numerator: u64,
        ratio_denominator: u64,
        max_order_iat: u64,
        valid_until: i64,
    ) -> Result<()> {
        validate_asset_policy(
            ratio_numerator,
            ratio_denominator,
            max_order_iat,
            valid_until,
            Clock::get()?.unix_timestamp,
            ctx.accounts.config.max_order_iat,
        )?;
        require_keys_neq!(
            ctx.accounts.input_mint.key(),
            ctx.accounts.config.iat_mint,
            CheckoutError::InputMintIsIat
        );

        let asset = &mut ctx.accounts.asset;
        asset.config = ctx.accounts.config.key();
        asset.input_mint = ctx.accounts.input_mint.key();
        asset.treasury_input_vault = ctx.accounts.treasury_input_vault.key();
        asset.token_program = ctx.accounts.input_token_program.key();
        asset.ratio_numerator = ratio_numerator;
        asset.ratio_denominator = ratio_denominator;
        asset.max_order_iat = max_order_iat;
        asset.valid_until = valid_until;
        asset.enabled = true;
        asset.bump = ctx.bumps.asset;
        Ok(())
    }

    pub fn update_asset(
        ctx: Context<UpdateAsset>,
        ratio_numerator: u64,
        ratio_denominator: u64,
        max_order_iat: u64,
        valid_until: i64,
        enabled: bool,
    ) -> Result<()> {
        validate_asset_policy(
            ratio_numerator,
            ratio_denominator,
            max_order_iat,
            valid_until,
            Clock::get()?.unix_timestamp,
            ctx.accounts.config.max_order_iat,
        )?;
        let asset = &mut ctx.accounts.asset;
        asset.ratio_numerator = ratio_numerator;
        asset.ratio_denominator = ratio_denominator;
        asset.max_order_iat = max_order_iat;
        asset.valid_until = valid_until;
        asset.enabled = enabled;
        Ok(())
    }

    pub fn initialize_wallet_usage(ctx: Context<InitializeWalletUsage>) -> Result<()> {
        let usage = &mut ctx.accounts.wallet_usage;
        usage.config = ctx.accounts.config.key();
        usage.buyer = ctx.accounts.buyer.key();
        usage.day = 0;
        usage.used_iat = 0;
        usage.bump = ctx.bumps.wallet_usage;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn execute_treasury_checkout(
        ctx: Context<ExecuteTreasuryCheckout>,
        order_hash: [u8; 32],
        quote_hash: [u8; 32],
        nonce: u64,
        input_amount: u64,
        iat_amount: u64,
        expires_at: i64,
    ) -> Result<()> {
        let clock = Clock::get()?;
        require!(!ctx.accounts.config.paused, CheckoutError::ProtocolPaused);
        require!(
            iat_amount > 0 && input_amount > 0,
            CheckoutError::InvalidAmount
        );
        require!(
            clock.unix_timestamp < expires_at,
            CheckoutError::QuoteExpired
        );
        require!(
            expires_at <= ctx.accounts.asset.valid_until,
            CheckoutError::AssetPriceExpired
        );
        require!(ctx.accounts.asset.enabled, CheckoutError::AssetDisabled);
        require!(
            iat_amount <= ctx.accounts.config.max_order_iat
                && iat_amount <= ctx.accounts.asset.max_order_iat,
            CheckoutError::OrderCapExceeded
        );
        require!(order_hash != [0; 32], CheckoutError::InvalidOrderHash);
        require!(quote_hash != [0; 32], CheckoutError::InvalidQuoteHash);
        require_keys_neq!(
            ctx.accounts.buyer_input.key(),
            ctx.accounts.treasury_input_vault.key(),
            CheckoutError::DuplicateAccount
        );
        require_keys_neq!(
            ctx.accounts.treasury_iat_vault.key(),
            ctx.accounts.settlement_escrow.key(),
            CheckoutError::DuplicateAccount
        );

        let required_input = calculate_required_input(
            iat_amount,
            ctx.accounts.asset.ratio_numerator,
            ctx.accounts.asset.ratio_denominator,
        )?;
        require!(
            input_amount == required_input,
            CheckoutError::IncorrectInputAmount
        );
        require!(
            ctx.accounts.treasury_iat_vault.amount >= iat_amount,
            CheckoutError::TreasuryInventoryInsufficient
        );

        let day = clock.unix_timestamp.div_euclid(SECONDS_PER_DAY);
        apply_usage_limits(
            &mut ctx.accounts.config,
            &mut ctx.accounts.wallet_usage,
            day,
            iat_amount,
        )?;

        let input_decimals = ctx.accounts.input_mint.decimals;
        let input_transfer = TransferChecked {
            from: ctx.accounts.buyer_input.to_account_info(),
            mint: ctx.accounts.input_mint.to_account_info(),
            to: ctx.accounts.treasury_input_vault.to_account_info(),
            authority: ctx.accounts.buyer.to_account_info(),
        };
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.input_token_program.to_account_info(),
                input_transfer,
            ),
            input_amount,
            input_decimals,
        )?;

        let config_key = ctx.accounts.config.key();
        let signer_seeds: &[&[u8]] = &[
            b"vault-authority",
            config_key.as_ref(),
            &[ctx.accounts.config.vault_authority_bump],
        ];
        let signer = &[signer_seeds];
        let iat_transfer = TransferChecked {
            from: ctx.accounts.treasury_iat_vault.to_account_info(),
            mint: ctx.accounts.iat_mint.to_account_info(),
            to: ctx.accounts.settlement_escrow.to_account_info(),
            authority: ctx.accounts.vault_authority.to_account_info(),
        };
        token_interface::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.iat_token_program.to_account_info(),
                iat_transfer,
                signer,
            ),
            iat_amount,
            ctx.accounts.iat_mint.decimals,
        )?;

        let payment = &mut ctx.accounts.payment_intent;
        payment.config = ctx.accounts.config.key();
        payment.order_hash = order_hash;
        payment.quote_hash = quote_hash;
        payment.buyer = ctx.accounts.buyer.key();
        payment.input_mint = ctx.accounts.input_mint.key();
        payment.input_amount = input_amount;
        payment.iat_amount = iat_amount;
        payment.nonce = nonce;
        payment.executed_at = clock.unix_timestamp;
        payment.bump = ctx.bumps.payment_intent;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn purchase_iat_with_usdc(
        ctx: Context<PurchaseIatWithUsdc>,
        order_hash: [u8; 32],
        quote_hash: [u8; 32],
        nonce: u64,
        input_amount: u64,
        iat_amount: u64,
        expires_at: i64,
    ) -> Result<()> {
        let clock = Clock::get()?;
        require!(!ctx.accounts.config.paused, CheckoutError::ProtocolPaused);
        require!(
            iat_amount > 0 && input_amount > 0,
            CheckoutError::InvalidAmount
        );
        require!(
            clock.unix_timestamp < expires_at,
            CheckoutError::QuoteExpired
        );
        require!(
            expires_at <= ctx.accounts.asset.valid_until,
            CheckoutError::AssetPriceExpired
        );
        require!(ctx.accounts.asset.enabled, CheckoutError::AssetDisabled);
        require!(
            iat_amount <= ctx.accounts.config.max_order_iat
                && iat_amount <= ctx.accounts.asset.max_order_iat,
            CheckoutError::OrderCapExceeded
        );
        require!(order_hash != [0; 32], CheckoutError::InvalidOrderHash);
        require!(quote_hash != [0; 32], CheckoutError::InvalidQuoteHash);
        require_keys_neq!(
            ctx.accounts.buyer_input.key(),
            ctx.accounts.treasury_input_vault.key(),
            CheckoutError::DuplicateAccount
        );
        require_keys_neq!(
            ctx.accounts.treasury_iat_vault.key(),
            ctx.accounts.buyer_iat_destination.key(),
            CheckoutError::DuplicateAccount
        );

        let required_input = calculate_required_input(
            iat_amount,
            ctx.accounts.asset.ratio_numerator,
            ctx.accounts.asset.ratio_denominator,
        )?;
        require!(
            input_amount == required_input,
            CheckoutError::IncorrectInputAmount
        );
        require!(
            ctx.accounts.treasury_iat_vault.amount >= iat_amount,
            CheckoutError::TreasuryInventoryInsufficient
        );

        let day = clock.unix_timestamp.div_euclid(SECONDS_PER_DAY);
        apply_usage_limits(
            &mut ctx.accounts.config,
            &mut ctx.accounts.wallet_usage,
            day,
            iat_amount,
        )?;

        let input_transfer = TransferChecked {
            from: ctx.accounts.buyer_input.to_account_info(),
            mint: ctx.accounts.input_mint.to_account_info(),
            to: ctx.accounts.treasury_input_vault.to_account_info(),
            authority: ctx.accounts.buyer.to_account_info(),
        };
        token_interface::transfer_checked(
            CpiContext::new(
                ctx.accounts.input_token_program.to_account_info(),
                input_transfer,
            ),
            input_amount,
            ctx.accounts.input_mint.decimals,
        )?;

        let config_key = ctx.accounts.config.key();
        let signer_seeds: &[&[u8]] = &[
            b"vault-authority",
            config_key.as_ref(),
            &[ctx.accounts.config.vault_authority_bump],
        ];
        let signer = &[signer_seeds];
        let iat_transfer = TransferChecked {
            from: ctx.accounts.treasury_iat_vault.to_account_info(),
            mint: ctx.accounts.iat_mint.to_account_info(),
            to: ctx.accounts.buyer_iat_destination.to_account_info(),
            authority: ctx.accounts.vault_authority.to_account_info(),
        };
        token_interface::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.iat_token_program.to_account_info(),
                iat_transfer,
                signer,
            ),
            iat_amount,
            ctx.accounts.iat_mint.decimals,
        )?;

        let payment = &mut ctx.accounts.payment_intent;
        payment.config = ctx.accounts.config.key();
        payment.order_hash = order_hash;
        payment.quote_hash = quote_hash;
        payment.buyer = ctx.accounts.buyer.key();
        payment.input_mint = ctx.accounts.input_mint.key();
        payment.input_amount = input_amount;
        payment.iat_amount = iat_amount;
        payment.nonce = nonce;
        payment.executed_at = clock.unix_timestamp;
        payment.bump = ctx.bumps.payment_intent;
        Ok(())
    }

    pub fn set_paused(ctx: Context<AdminConfig>, paused: bool) -> Result<()> {
        ctx.accounts.config.paused = paused;
        Ok(())
    }

    pub fn set_quote_authority(ctx: Context<AdminConfig>, quote_authority: Pubkey) -> Result<()> {
        require!(
            quote_authority != Pubkey::default(),
            CheckoutError::InvalidAuthority
        );
        ctx.accounts.config.quote_authority = quote_authority;
        Ok(())
    }

    pub fn propose_authority(ctx: Context<AdminConfig>, pending_authority: Pubkey) -> Result<()> {
        require!(
            pending_authority != Pubkey::default(),
            CheckoutError::InvalidAuthority
        );
        require_keys_neq!(
            pending_authority,
            ctx.accounts.config.authority,
            CheckoutError::InvalidAuthority
        );
        ctx.accounts.config.pending_authority = pending_authority;
        Ok(())
    }

    pub fn accept_authority(ctx: Context<AcceptAuthority>) -> Result<()> {
        ctx.accounts.config.authority = ctx.accounts.pending_authority.key();
        ctx.accounts.config.pending_authority = Pubkey::default();
        Ok(())
    }
}

#[derive(Accounts)]
pub struct InitializeConfig<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,
    #[account(
        init,
        payer = authority,
        space = 8 + ProtocolConfig::INIT_SPACE,
        seeds = [b"config"],
        bump
    )]
    pub config: Box<Account<'info, ProtocolConfig>>,
    /// CHECK: PDA used only as a token-account authority; seeds are verified.
    #[account(
        seeds = [b"vault-authority", config.key().as_ref()],
        bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    pub iat_mint: InterfaceAccount<'info, Mint>,
    #[account(
        token::mint = iat_mint,
        token::authority = vault_authority,
        token::token_program = iat_token_program
    )]
    pub treasury_iat_vault: InterfaceAccount<'info, TokenAccount>,
    #[account(
        token::mint = iat_mint,
        token::token_program = iat_token_program
    )]
    pub settlement_escrow: InterfaceAccount<'info, TokenAccount>,
    pub iat_token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ConfigureAsset<'info> {
    #[account(
        mut,
        has_one = authority @ CheckoutError::Unauthorized
    )]
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub input_mint: InterfaceAccount<'info, Mint>,
    /// CHECK: PDA token authority validated by canonical seeds.
    #[account(
        seeds = [b"vault-authority", config.key().as_ref()],
        bump = config.vault_authority_bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    #[account(
        token::mint = input_mint,
        token::authority = vault_authority,
        token::token_program = input_token_program
    )]
    pub treasury_input_vault: InterfaceAccount<'info, TokenAccount>,
    pub input_token_program: Interface<'info, TokenInterface>,
    #[account(
        init,
        payer = authority,
        space = 8 + AssetConfig::INIT_SPACE,
        seeds = [b"asset", config.key().as_ref(), input_mint.key().as_ref()],
        bump
    )]
    pub asset: Box<Account<'info, AssetConfig>>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateAsset<'info> {
    #[account(has_one = authority @ CheckoutError::Unauthorized)]
    pub config: Account<'info, ProtocolConfig>,
    pub authority: Signer<'info>,
    #[account(
        mut,
        has_one = config @ CheckoutError::InvalidAsset,
        seeds = [b"asset", config.key().as_ref(), asset.input_mint.as_ref()],
        bump = asset.bump
    )]
    pub asset: Account<'info, AssetConfig>,
}

#[derive(Accounts)]
pub struct InitializeWalletUsage<'info> {
    pub config: Account<'info, ProtocolConfig>,
    #[account(mut)]
    pub buyer: Signer<'info>,
    #[account(
        init,
        payer = buyer,
        space = 8 + WalletUsage::INIT_SPACE,
        seeds = [b"wallet-usage", config.key().as_ref(), buyer.key().as_ref()],
        bump
    )]
    pub wallet_usage: Box<Account<'info, WalletUsage>>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(order_hash: [u8; 32], quote_hash: [u8; 32], nonce: u64)]
pub struct ExecuteTreasuryCheckout<'info> {
    #[account(mut)]
    pub buyer: Signer<'info>,
    #[account(
        address = config.quote_authority @ CheckoutError::UnauthorizedQuote
    )]
    pub quote_authority: Signer<'info>,
    #[account(
        mut,
        seeds = [b"config"],
        bump = config.bump
    )]
    pub config: Box<Account<'info, ProtocolConfig>>,
    #[account(
        seeds = [b"asset", config.key().as_ref(), input_mint.key().as_ref()],
        bump = asset.bump,
        has_one = config @ CheckoutError::InvalidAsset,
        constraint = asset.input_mint == input_mint.key() @ CheckoutError::InvalidAsset
    )]
    pub asset: Box<Account<'info, AssetConfig>>,
    #[account(
        mut,
        seeds = [b"wallet-usage", config.key().as_ref(), buyer.key().as_ref()],
        bump = wallet_usage.bump,
        has_one = config @ CheckoutError::InvalidUsage,
        has_one = buyer @ CheckoutError::InvalidUsage
    )]
    pub wallet_usage: Box<Account<'info, WalletUsage>>,
    #[account(
        init,
        payer = buyer,
        space = 8 + PaymentIntent::INIT_SPACE,
        seeds = [
            b"payment",
            config.key().as_ref(),
            order_hash.as_ref(),
            buyer.key().as_ref(),
            nonce.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub payment_intent: Box<Account<'info, PaymentIntent>>,
    pub input_mint: Box<InterfaceAccount<'info, Mint>>,
    #[account(
        address = config.iat_mint @ CheckoutError::InvalidIatMint
    )]
    pub iat_mint: Box<InterfaceAccount<'info, Mint>>,
    #[account(
        mut,
        token::mint = input_mint,
        token::authority = buyer,
        token::token_program = input_token_program
    )]
    pub buyer_input: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        address = asset.treasury_input_vault @ CheckoutError::InvalidTreasuryVault,
        token::mint = input_mint,
        token::authority = vault_authority,
        token::token_program = input_token_program,
        constraint = input_token_program.key() == asset.token_program
            @ CheckoutError::InvalidTokenProgram
    )]
    pub treasury_input_vault: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        address = config.treasury_iat_vault @ CheckoutError::InvalidTreasuryVault,
        token::mint = iat_mint,
        token::authority = vault_authority,
        token::token_program = iat_token_program
    )]
    pub treasury_iat_vault: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        address = config.settlement_escrow @ CheckoutError::InvalidSettlementEscrow,
        token::mint = iat_mint,
        token::token_program = iat_token_program
    )]
    pub settlement_escrow: Box<InterfaceAccount<'info, TokenAccount>>,
    /// CHECK: PDA authority is validated by canonical seeds and never deserialized.
    #[account(
        seeds = [b"vault-authority", config.key().as_ref()],
        bump = config.vault_authority_bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    pub input_token_program: Interface<'info, TokenInterface>,
    pub iat_token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(order_hash: [u8; 32], quote_hash: [u8; 32], nonce: u64)]
pub struct PurchaseIatWithUsdc<'info> {
    #[account(mut)]
    pub buyer: Signer<'info>,
    #[account(
        mut,
        seeds = [b"config"],
        bump = config.bump
    )]
    pub config: Box<Account<'info, ProtocolConfig>>,
    #[account(
        seeds = [b"asset", config.key().as_ref(), input_mint.key().as_ref()],
        bump = asset.bump,
        has_one = config @ CheckoutError::InvalidAsset,
        constraint = asset.input_mint == input_mint.key() @ CheckoutError::InvalidAsset
    )]
    pub asset: Box<Account<'info, AssetConfig>>,
    #[account(
        mut,
        seeds = [b"wallet-usage", config.key().as_ref(), buyer.key().as_ref()],
        bump = wallet_usage.bump,
        has_one = config @ CheckoutError::InvalidUsage,
        has_one = buyer @ CheckoutError::InvalidUsage
    )]
    pub wallet_usage: Box<Account<'info, WalletUsage>>,
    #[account(
        init,
        payer = buyer,
        space = 8 + PaymentIntent::INIT_SPACE,
        seeds = [
            b"payment",
            config.key().as_ref(),
            order_hash.as_ref(),
            buyer.key().as_ref(),
            nonce.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub payment_intent: Box<Account<'info, PaymentIntent>>,
    pub input_mint: Box<InterfaceAccount<'info, Mint>>,
    #[account(
        address = config.iat_mint @ CheckoutError::InvalidIatMint
    )]
    pub iat_mint: Box<InterfaceAccount<'info, Mint>>,
    #[account(
        mut,
        token::mint = input_mint,
        token::authority = buyer,
        token::token_program = input_token_program
    )]
    pub buyer_input: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        address = asset.treasury_input_vault @ CheckoutError::InvalidTreasuryVault,
        token::mint = input_mint,
        token::authority = vault_authority,
        token::token_program = input_token_program,
        constraint = input_token_program.key() == asset.token_program
            @ CheckoutError::InvalidTokenProgram
    )]
    pub treasury_input_vault: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        address = config.treasury_iat_vault @ CheckoutError::InvalidTreasuryVault,
        token::mint = iat_mint,
        token::authority = vault_authority,
        token::token_program = iat_token_program
    )]
    pub treasury_iat_vault: Box<InterfaceAccount<'info, TokenAccount>>,
    #[account(
        mut,
        token::mint = iat_mint,
        token::authority = buyer,
        token::token_program = iat_token_program
    )]
    pub buyer_iat_destination: Box<InterfaceAccount<'info, TokenAccount>>,
    /// CHECK: PDA authority is validated by canonical seeds and never deserialized.
    #[account(
        seeds = [b"vault-authority", config.key().as_ref()],
        bump = config.vault_authority_bump
    )]
    pub vault_authority: UncheckedAccount<'info>,
    pub input_token_program: Interface<'info, TokenInterface>,
    pub iat_token_program: Interface<'info, TokenInterface>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AdminConfig<'info> {
    #[account(
        mut,
        has_one = authority @ CheckoutError::Unauthorized,
        seeds = [b"config"],
        bump = config.bump
    )]
    pub config: Account<'info, ProtocolConfig>,
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct AcceptAuthority<'info> {
    #[account(
        mut,
        seeds = [b"config"],
        bump = config.bump,
        constraint = config.pending_authority == pending_authority.key()
            @ CheckoutError::Unauthorized
    )]
    pub config: Account<'info, ProtocolConfig>,
    pub pending_authority: Signer<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct ProtocolConfig {
    pub authority: Pubkey,
    pub pending_authority: Pubkey,
    pub quote_authority: Pubkey,
    pub iat_mint: Pubkey,
    pub treasury_iat_vault: Pubkey,
    pub settlement_escrow: Pubkey,
    pub max_order_iat: u64,
    pub wallet_daily_iat_cap: u64,
    pub treasury_daily_iat_cap: u64,
    pub treasury_usage_day: i64,
    pub treasury_usage_iat: u64,
    pub paused: bool,
    pub bump: u8,
    pub vault_authority_bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct AssetConfig {
    pub config: Pubkey,
    pub input_mint: Pubkey,
    pub treasury_input_vault: Pubkey,
    pub token_program: Pubkey,
    pub ratio_numerator: u64,
    pub ratio_denominator: u64,
    pub max_order_iat: u64,
    pub valid_until: i64,
    pub enabled: bool,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct WalletUsage {
    pub config: Pubkey,
    pub buyer: Pubkey,
    pub day: i64,
    pub used_iat: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct PaymentIntent {
    pub config: Pubkey,
    pub order_hash: [u8; 32],
    pub quote_hash: [u8; 32],
    pub buyer: Pubkey,
    pub input_mint: Pubkey,
    pub input_amount: u64,
    pub iat_amount: u64,
    pub nonce: u64,
    pub executed_at: i64,
    pub bump: u8,
}

fn calculate_required_input(
    iat_amount: u64,
    ratio_numerator: u64,
    ratio_denominator: u64,
) -> Result<u64> {
    require!(
        ratio_numerator > 0 && ratio_denominator > 0,
        CheckoutError::InvalidPriceRatio
    );
    let product = u128::from(iat_amount)
        .checked_mul(u128::from(ratio_numerator))
        .ok_or(CheckoutError::ArithmeticOverflow)?;
    let rounded = product
        .checked_add(u128::from(ratio_denominator - 1))
        .ok_or(CheckoutError::ArithmeticOverflow)?
        .checked_div(u128::from(ratio_denominator))
        .ok_or(CheckoutError::InvalidPriceRatio)?;
    u64::try_from(rounded).map_err(|_| CheckoutError::ArithmeticOverflow.into())
}

fn validate_asset_policy(
    ratio_numerator: u64,
    ratio_denominator: u64,
    max_order_iat: u64,
    valid_until: i64,
    now: i64,
    protocol_max_order_iat: u64,
) -> Result<()> {
    require!(
        ratio_numerator > 0 && ratio_denominator > 0,
        CheckoutError::InvalidPriceRatio
    );
    require!(
        max_order_iat > 0 && max_order_iat <= protocol_max_order_iat,
        CheckoutError::InvalidLimit
    );
    require!(valid_until > now, CheckoutError::AssetPriceExpired);
    require!(
        valid_until - now <= MAX_ASSET_POLICY_LIFETIME_SECONDS,
        CheckoutError::AssetPolicyTooLong
    );
    Ok(())
}

fn apply_usage_limits(
    config: &mut ProtocolConfig,
    wallet: &mut WalletUsage,
    day: i64,
    amount: u64,
) -> Result<()> {
    let treasury_current = if config.treasury_usage_day == day {
        config.treasury_usage_iat
    } else {
        0
    };
    let wallet_current = if wallet.day == day {
        wallet.used_iat
    } else {
        0
    };
    let treasury_next = treasury_current
        .checked_add(amount)
        .ok_or(CheckoutError::ArithmeticOverflow)?;
    let wallet_next = wallet_current
        .checked_add(amount)
        .ok_or(CheckoutError::ArithmeticOverflow)?;
    require!(
        treasury_next <= config.treasury_daily_iat_cap,
        CheckoutError::TreasuryDailyCapExceeded
    );
    require!(
        wallet_next <= config.wallet_daily_iat_cap,
        CheckoutError::WalletDailyCapExceeded
    );
    config.treasury_usage_day = day;
    config.treasury_usage_iat = treasury_next;
    wallet.day = day;
    wallet.used_iat = wallet_next;
    Ok(())
}

#[error_code]
pub enum CheckoutError {
    #[msg("The protocol checkout is paused")]
    ProtocolPaused,
    #[msg("The signer is not authorized")]
    Unauthorized,
    #[msg("The checkout quote lacks protocol authorization")]
    UnauthorizedQuote,
    #[msg("The configured authority is invalid")]
    InvalidAuthority,
    #[msg("The amount must be positive")]
    InvalidAmount,
    #[msg("The configured limit is invalid")]
    InvalidLimit,
    #[msg("The price ratio is invalid")]
    InvalidPriceRatio,
    #[msg("The configured asset is invalid")]
    InvalidAsset,
    #[msg("The configured asset is disabled")]
    AssetDisabled,
    #[msg("The configured asset price has expired")]
    AssetPriceExpired,
    #[msg("The configured asset policy lifetime is too long")]
    AssetPolicyTooLong,
    #[msg("The quote has expired")]
    QuoteExpired,
    #[msg("The order amount exceeds its cap")]
    OrderCapExceeded,
    #[msg("The input amount does not match the governed price")]
    IncorrectInputAmount,
    #[msg("The wallet daily cap would be exceeded")]
    WalletDailyCapExceeded,
    #[msg("The treasury daily cap would be exceeded")]
    TreasuryDailyCapExceeded,
    #[msg("The treasury IAT inventory is insufficient")]
    TreasuryInventoryInsufficient,
    #[msg("The input mint cannot be IAT")]
    InputMintIsIat,
    #[msg("The IAT mint is invalid")]
    InvalidIatMint,
    #[msg("The settlement escrow is invalid")]
    InvalidSettlementEscrow,
    #[msg("The treasury vault is invalid")]
    InvalidTreasuryVault,
    #[msg("The token program is invalid")]
    InvalidTokenProgram,
    #[msg("The wallet usage account is invalid")]
    InvalidUsage,
    #[msg("Mutable accounts must be distinct")]
    DuplicateAccount,
    #[msg("The order hash cannot be zero")]
    InvalidOrderHash,
    #[msg("The quote hash cannot be zero")]
    InvalidQuoteHash,
    #[msg("Arithmetic overflow")]
    ArithmeticOverflow,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> ProtocolConfig {
        ProtocolConfig {
            authority: Pubkey::new_unique(),
            pending_authority: Pubkey::default(),
            quote_authority: Pubkey::new_unique(),
            iat_mint: Pubkey::new_unique(),
            treasury_iat_vault: Pubkey::new_unique(),
            settlement_escrow: Pubkey::new_unique(),
            max_order_iat: 10_000,
            wallet_daily_iat_cap: 20_000,
            treasury_daily_iat_cap: 50_000,
            treasury_usage_day: 0,
            treasury_usage_iat: 0,
            paused: false,
            bump: 1,
            vault_authority_bump: 2,
        }
    }

    fn wallet(config_key: Pubkey, buyer: Pubkey) -> WalletUsage {
        WalletUsage {
            config: config_key,
            buyer,
            day: 0,
            used_iat: 0,
            bump: 3,
        }
    }

    #[test]
    fn required_input_rounds_up_and_never_undercharges() {
        assert_eq!(calculate_required_input(10, 1, 3).unwrap(), 4);
        assert_eq!(
            calculate_required_input(100_000_000, 25, 10_000).unwrap(),
            250_000
        );
    }

    #[test]
    fn invalid_and_overflowing_ratios_fail_closed() {
        assert!(calculate_required_input(10, 1, 0).is_err());
        assert!(calculate_required_input(u64::MAX, u64::MAX, 1).is_err());
    }

    #[test]
    fn usage_limits_accumulate_and_reset_only_on_a_new_day() {
        let mut protocol = config();
        let mut usage = wallet(Pubkey::new_unique(), Pubkey::new_unique());
        apply_usage_limits(&mut protocol, &mut usage, 100, 5_000).unwrap();
        apply_usage_limits(&mut protocol, &mut usage, 100, 5_000).unwrap();
        assert_eq!(usage.used_iat, 10_000);
        assert_eq!(protocol.treasury_usage_iat, 10_000);

        apply_usage_limits(&mut protocol, &mut usage, 101, 7_000).unwrap();
        assert_eq!(usage.used_iat, 7_000);
        assert_eq!(protocol.treasury_usage_iat, 7_000);
    }

    #[test]
    fn wallet_and_treasury_caps_fail_without_mutating_counters() {
        let mut protocol = config();
        let mut usage = wallet(Pubkey::new_unique(), Pubkey::new_unique());
        usage.used_iat = 19_000;
        usage.day = 10;
        protocol.treasury_usage_day = 10;
        protocol.treasury_usage_iat = 49_000;

        assert!(apply_usage_limits(&mut protocol, &mut usage, 10, 2_000).is_err());
        assert_eq!(usage.used_iat, 19_000);
        assert_eq!(protocol.treasury_usage_iat, 49_000);
    }

    #[test]
    fn asset_policy_must_be_fresh_bounded_and_positive() {
        assert!(validate_asset_policy(1, 1, 100, 101, 100, 100).is_ok());
        assert!(validate_asset_policy(0, 1, 100, 101, 100, 100).is_err());
        assert!(validate_asset_policy(1, 1, 101, 101, 100, 100).is_err());
        assert!(validate_asset_policy(1, 1, 100, 100, 100, 100).is_err());
        assert!(validate_asset_policy(1, 1, 100, 1001, 100, 100).is_err());
    }
}

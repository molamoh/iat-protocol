from setuptools import setup, find_packages

setup(
    name="iat-protocol",
    version="1.0.0",
    author="Anonymous Founder",
    description="IAT Protocol SDK — The first AI-native blockchain protocol",
    long_description="Transactions between AI agents validate the network. Zero human intervention.",
    url="https://github.com/molamoh/iat-protocol",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "solana",
        "solders",
        "cryptography",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    keywords="blockchain solana AI agents payment protocol",
)

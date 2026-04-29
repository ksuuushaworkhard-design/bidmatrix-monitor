from setuptools import find_packages, setup


setup(
    name="bidmatrix-news-monitoring",
    version="0.1.0",
    description="AI-powered news monitoring and market intelligence workflow for BidMatrix.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=[
        "exa-py>=1.14.0",
        "python-dotenv>=1.0.1",
    ],
    extras_require={
        "dev": ["pytest>=8.0.0"],
    },
    entry_points={
        "console_scripts": [
            "bidmatrix-monitor=bidmatrix_monitor.cli:main",
        ],
    },
)

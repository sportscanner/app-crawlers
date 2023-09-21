from setuptools import find_packages, setup

install_requires = open("requirements.txt").read().strip().split("\n")

setup(
    # Package metadata
    name="shuttlebot",
    version="0.2.0",
    description="Badminton slots scanner for Better Org. leisure centres in London",
    author="Yasir Khalid",
    author_email="yasir_khalid@outlook.com",
    url="https://github.com/yasir-khalid/badminton-slots-scanner",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    # Package setup
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    # Requirements
    python_requires=">=3.8",
    install_requires=install_requires,
    classifiers=[
        "Natural Language :: English",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries",
    ],
    download_url="https://github.com/yasir-khalid/badminton-slots-scanner",
)

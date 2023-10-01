from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="shuttlebot",
    version="0.1.0",
    description="Webapp that helps badminton players in London find consecutively available badminton slots for the "
                "upcoming week",
    author="Yasir Khalid",
    author_email="yasir_khalid@outlook.com",
    url="https://github.com/yasir-khalid/badminton-slots-scanner",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    install_requires=install_requires,
    python_requires=">=3.10",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries",
    ],
)

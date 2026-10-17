from setuptools import setup, find_packages

setup(
    name='shizuha-storage',
    version='1.0.0',
    description='Shared MinIO/S3 storage and quota utilities for Shizuha platform',
    author='Shizuha Team',
    author_email='dev@shizuha.com',
    packages=find_packages(),
    python_requires='>=3.10',
    install_requires=[
        'Django>=4.2',
        'requests>=2.31',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Framework :: Django :: 4.2',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)

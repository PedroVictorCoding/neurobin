#!/usr/bin/env python3
"""
Setup script for ChemBio Importer
"""

from setuptools import setup, find_packages
import os

# Read README for long description
def read_readme():
    with open('README.md', 'r', encoding='utf-8') as f:
        return f.read()

# Read requirements
def read_requirements():
    with open('requirements.txt', 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='chembio-importer',
    version='1.0.0',
    description='A comprehensive tool for importing and cross-referencing compound data from ChEMBL and Reactome',
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    author='ChemBio Importer Team',
    author_email='contact@example.com',
    url='https://github.com/yourusername/chembio-importer',
    packages=find_packages(),
    include_package_data=True,
    install_requires=read_requirements(),
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        'Topic :: Scientific/Engineering :: Chemistry',
        'Topic :: Database',
    ],
    keywords='chembl reactome biochemistry compounds pathways bioinformatics',
    entry_points={
        'console_scripts': [
            'chembio-importer=chembio_importer.__main__:main',
        ],
    },
    project_urls={
        'Bug Reports': 'https://github.com/yourusername/chembio-importer/issues',
        'Source': 'https://github.com/yourusername/chembio-importer',
        'Documentation': 'https://github.com/yourusername/chembio-importer#readme',
    },
)

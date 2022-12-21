"""Setup file for using congress as a python package."""
from os import path

import setuptools

# Obtain long_description from README.md
here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setuptools.setup(
    name='united-states-congress',
    version='0.0.1',
    author='The unitedstates organization on GitHub',
    long_description=long_description,
    description='Public domain data collectors for the work of Congress, '
    'including legislation, amendments, and votes.',
    license='CC0-1.0',
    packages=setuptools.find_packages(),
    install_requires=[
        'beautifulsoup4',
        'cssselect',
        'iso8601',
        'lxml',
        'mechanize',
        'mock',
        'rtyaml',
        'python-dateutil',
        'pytz',
        'pyyaml',
        'scrapelib',
        'xmltodict',
        'packaging',
    ],
    entry_points={
        'console_scripts': [
            'usc-run=congress.run:main'
        ],
    },
    scripts=[
        'scripts/bills.sh',
        'scripts/statutes.sh',
        'scripts/votes.sh',
        'scripts/voteview.sh'
    ],
)

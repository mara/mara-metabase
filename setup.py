from setuptools import setup, find_packages
import re

def get_long_description():
    with open('README.md') as f:
        return re.sub('!\[(.*?)\]\(docs/(.*?)\)', r'![\1](https://github.com/mara/mara-metabase/raw/master/docs/\2)', f.read())

setup(
    name='mara-metabase',
    version='2.0.0',

    description='Configuring Metabase from Python',

    long_description=get_long_description(),
    long_description_content_type='text/markdown',

    url = 'https://github.com/mara/mara-metabase',

    install_requires=[
        'mara-db>=4.7.1',
        'mara-page',
        'sympy',
        'bcrypt',
        'requests'
    ],

    python_requires='>=3.6',

    packages=find_packages(),

    author='Mara contributors',
    license='MIT',

    entry_points={},
)


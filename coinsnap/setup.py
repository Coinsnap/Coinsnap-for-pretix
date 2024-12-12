from setuptools import setup, find_packages

setup(
    name='pretix-coinsnap',
    version='1.0.0',
    description='A Pretix plugin for proof of concept',
    include_package_data=True,
    entry_points={
        'pretix.plugin': [
            'coinsnap=coinsnap:CoinSnapPluginMeta',
        ],
    },
)
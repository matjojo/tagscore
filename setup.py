# type: ignore
from setuptools import setup

setup(
   name='hydrus-tagscore',
   version='1.0',
   description='Take scores for tags, give scores to images',
   author='Matjojo',
   packages=['hydrus-tagscore'],  # same as name
   install_requires=['hydrus-api'], # external packages as dependencies
)
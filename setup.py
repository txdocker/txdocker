from setuptools import setup, find_packages


exec(open('txdocker/version.py').read())

with open('./requirements.txt') as test_reqs_txt:
    install_requirements = [line for line in test_reqs_txt]

with open('./test-requirements.txt') as test_reqs_txt:
    test_requirements = [line for line in test_reqs_txt]

setup(
    name='txdocker',
    version=version,
    description="A Twisted client for Docker.",
    author='Greg Taylor',
    author_email='gtaylor@gc-taylor.com',
    url='https://github.com/gtaylor/txdocker',
    packages=find_packages(exclude=['ez_setup', 'tests']),
    install_requires=install_requirements,
    tests_require=test_requirements,
    test_suite='tests',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Other Environment',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Topic :: Utilities',
        'License :: OSI Approved :: Apache Software License',
    ],
)

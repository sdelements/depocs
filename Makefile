lint:
	find . -name '*.py' | egrep -v './doc' | xargs flake8 --ignore=E501,W601

test:
	python ./setup.py test

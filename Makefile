lint:
	black .
	find . -name '*.py' | egrep -v './docs' | xargs flake8 --extend-ignore=D,E501,W601 --statistics --count

test:
	python -m unittest discover

lint:
	find . -name '*.py' | egrep -v './docs' | xargs flake8 --extend-ignore=E501,W601 --statistics --count

test:
	pytest --cov-report=html --cov-report=term --cov=depocs

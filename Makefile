lint:
	black .
	flake8 . --extend-ignore=D,E501,W601 --extend-exclude=docs/ --statistics --count

test:
	python -m unittest discover

security:
	bandit -c pyproject.toml -r .

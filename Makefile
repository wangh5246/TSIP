.PHONY: test-fast build-settlement setup-settlement prove-settlement

test-fast:
	pytest -q \
		tests/test_settlement_architecture.py \
		tests/test_charger_service.py \
		tests/test_eval_harness.py \
		tests/test_eval_experiments.py \
		tests/test_trajectory_preprocess.py

build-settlement:
	bash script/build_settlement_period_v5.sh

setup-settlement:
	bash script/setup_settlement_period_v5.sh

prove-settlement:
	python3 script/prove_settlement_period_v5.py

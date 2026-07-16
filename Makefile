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
.PHONY: waybill-config waybill-test waybill-ci waybill-image waybill-data-manifest waybill-plan

waybill-config:
	python script/waybill_formal.py validate-config

waybill-test:
	script/run_pytests.sh

waybill-ci:
	script/ci_local.sh

waybill-image:
	docker buildx build --provenance=false --platform linux/amd64 --load \
		-t waybill-formal:local \
		-f containers/waybill-formal/Dockerfile .

waybill-data-manifest:
	test -n "$(WAYBILL_DATA_ROOT)"
	python script/waybill_formal.py build-data-manifest \
		--data-root "$(WAYBILL_DATA_ROOT)" \
		--output-dir artifacts/waybill_formal/data

waybill-plan:
	test -n "$(WAYBILL_PREPARED_MANIFEST)"
	python script/waybill_formal.py plan \
		--prepared-manifest "$(WAYBILL_PREPARED_MANIFEST)" \
		--output-dir artifacts/waybill_formal/plan

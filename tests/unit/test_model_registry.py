"""
QUANT HERMES — TESTES DO REGISTRO DE MODELOS E ROLLBACK
Módulo: tests.unit.test_model_registry
"""
import shutil
import tempfile
from pathlib import Path
import pytest
from sklearn.linear_model import LogisticRegression

from intelligence.learning.monte_carlo import MonteCarloReport
from intelligence.learning.registry import ModelMetadata, ModelRegistry, ModelStage
from intelligence.learning.validation import ValidationReport


@pytest.fixture
def temp_registry():
    temp_dir = tempfile.mkdtemp()
    registry = ModelRegistry(base_storage_dir=temp_dir)
    yield registry
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def dummy_model():
    model = LogisticRegression()
    # Treina com dados mínimos para poder serializar
    model.fit([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]], [0, 1, 1])
    return model


class TestModelRegistry:

    def test_register_candidate_creates_files_and_checksum(self, temp_registry, dummy_model):
        meta = temp_registry.register_candidate(
            model=dummy_model,
            symbol="EURUSD",
            engine="logistic_regression",
            hyperparameters={"C": 1.0},
            model_id="test_candidate_v1",
        )

        assert meta.model_id == "test_candidate_v1"
        assert meta.symbol == "EURUSD"
        assert meta.stage == ModelStage.CANDIDATE
        assert len(meta.sha256_checksum) == 64

        # Verifica persistência no disco
        model_file = temp_registry.base_dir / "EURUSD" / "test_candidate_v1" / "model.joblib"
        meta_file = temp_registry.base_dir / "EURUSD" / "test_candidate_v1" / "metadata.json"
        assert model_file.exists()
        assert meta_file.exists()

    def test_rule_15_rejection_blocks_unapproved_model(self, temp_registry, dummy_model):
        temp_registry.register_candidate(
            model=dummy_model,
            symbol="EURUSD",
            engine="lightgbm",
            hyperparameters={},
            model_id="candidate_fail",
        )

        failing_val_report = ValidationReport(
            is_approved_for_production=False,
            rejection_reasons=["Profit Factor OOS 1.05 < 1.30"],
            total_folds=3,
            mean_profit_factor=1.05,
            mean_win_rate=0.48,
            mean_sharpe=0.8,
            max_drawdown_observed=0.06,
            total_oos_trades=25,
            fold_results=[],
        )

        # Deve levantar PermissionError bloqueando a violação da Regra 15
        with pytest.raises(PermissionError, match="Constitutional Violation"):
            temp_registry.promote_to_production(
                symbol="EURUSD",
                model_id="candidate_fail",
                validation_report=failing_val_report,
            )

        # O modelo deve estar marcado como REJECTED
        models = temp_registry.list_models("EURUSD")
        cand = [m for m in models if m.model_id == "candidate_fail"][0]
        assert cand.stage == ModelStage.REJECTED

    def test_promotion_and_atomic_rollback(self, temp_registry, dummy_model):
        # 1. Registra e promove V1
        temp_registry.register_candidate(
            model=dummy_model,
            symbol="EURUSD",
            engine="lightgbm",
            hyperparameters={},
            model_id="model_v1",
        )

        approved_report = ValidationReport(
            is_approved_for_production=True,
            rejection_reasons=[],
            total_folds=3,
            mean_profit_factor=1.65,
            mean_win_rate=0.58,
            mean_sharpe=1.8,
            max_drawdown_observed=0.04,
            total_oos_trades=35,
            fold_results=[],
        )

        v1_meta = temp_registry.promote_to_production(
            symbol="EURUSD",
            model_id="model_v1",
            validation_report=approved_report,
        )
        assert v1_meta.stage == ModelStage.PRODUCTION

        # 2. Registra e promove V2
        temp_registry.register_candidate(
            model=dummy_model,
            symbol="EURUSD",
            engine="lightgbm",
            hyperparameters={},
            model_id="model_v2",
        )
        temp_registry.promote_to_production(
            symbol="EURUSD",
            model_id="model_v2",
            validation_report=approved_report,
        )

        # V2 agora é PRODUCTION e V1 é ARCHIVED
        prod = temp_registry.get_production_metadata("EURUSD")
        assert prod.model_id == "model_v2"

        models = temp_registry.list_models("EURUSD")
        v1_state = [m for m in models if m.model_id == "model_v1"][0]
        assert v1_state.stage == ModelStage.ARCHIVED

        # 3. Executa Rollback por anomalia
        restored_id = temp_registry.rollback_production_model(
            symbol="EURUSD",
            reason="Degradação de performance detectada no live paper trading",
        )
        assert restored_id == "model_v1"

        # V1 voltou a ser PRODUCTION, V2 foi REJECTED
        new_prod = temp_registry.get_production_metadata("EURUSD")
        assert new_prod.model_id == "model_v1"
        assert new_prod.stage == ModelStage.PRODUCTION

        # Carrega modelo e valida integridade SHA256
        loaded = temp_registry.load_production_model("EURUSD")
        assert loaded is not None

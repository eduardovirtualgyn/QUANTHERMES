"""
QUANT HERMES — REGISTRO DE MODELOS E MECANISMO DE ROLLBACK
Módulo: intelligence.learning.registry

Implementa conformidade estrita com a Regra 15 da Constituição de Engenharia:
'Modelos de produção só são substituídos após aprovação em testes de validação
purgada fora da amostra com mecanismo de rollback.'
"""
from __future__ import annotations

import enum
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import joblib

from core.logger import get_logger
from intelligence.learning.monte_carlo import MonteCarloReport
from intelligence.learning.validation import ValidationReport

logger = get_logger("model_registry")


class ModelStage(str, enum.Enum):
    """Estágios do ciclo de vida de um modelo de Machine Learning."""
    CANDIDATE = "CANDIDATE"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


@dataclass
class ModelMetadata:
    """Metadados de auditoria e governança de um modelo quantitativo."""
    model_id: str
    symbol: str
    engine: str
    stage: ModelStage
    created_at_utc: str
    sha256_checksum: str
    hyperparameters: Dict[str, Any]
    oos_metrics: Dict[str, Any]
    validation_status: str
    rejection_reasons: List[str] = field(default_factory=list)
    promoted_at_utc: Optional[str] = None
    rollback_history: List[Dict[str, str]] = field(default_factory=list)


class ModelRegistry:
    """
    Registro centralizado e imutável de modelos de Machine Learning.
    Controla o versionamento, validação formal e rollback automático.
    """

    def __init__(self, base_storage_dir: str = "data/models") -> None:
        self.base_dir = Path(base_storage_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, Any] = {}

    def _get_symbol_dir(self, symbol: str) -> Path:
        sym_dir = self.base_dir / symbol.upper()
        sym_dir.mkdir(parents=True, exist_ok=True)
        return sym_dir

    def _calculate_sha256(self, file_path: Path) -> str:
        """Calcula o hash SHA256 do arquivo para garantia de integridade."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def register_candidate(
        self,
        model: Any,
        symbol: str,
        engine: str,
        hyperparameters: Dict[str, Any],
        model_id: Optional[str] = None,
    ) -> ModelMetadata:
        """
        Registra um novo modelo candidato em disco com metadados iniciais.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        m_id = model_id or f"{symbol.upper()}_{engine}_{timestamp}"
        model_dir = self._get_symbol_dir(symbol) / m_id
        model_dir.mkdir(parents=True, exist_ok=True)

        model_file = model_dir / "model.joblib"
        joblib.dump(model, model_file)

        checksum = self._calculate_sha256(model_file)

        metadata = ModelMetadata(
            model_id=m_id,
            symbol=symbol.upper(),
            engine=engine,
            stage=ModelStage.CANDIDATE,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            sha256_checksum=checksum,
            hyperparameters=hyperparameters,
            oos_metrics={},
            validation_status="PENDING_VALIDATION",
        )

        meta_file = model_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            meta_dict = asdict(metadata)
            meta_dict["stage"] = metadata.stage.value
            json.dump(meta_dict, f, indent=2)

        logger.info(
            "Modelo candidato registrado com sucesso",
            extra={"model_id": m_id, "symbol": symbol, "checksum": checksum[:8]},
        )
        return metadata

    def promote_to_production(
        self,
        symbol: str,
        model_id: str,
        validation_report: ValidationReport,
        monte_carlo_report: Optional[MonteCarloReport] = None,
    ) -> ModelMetadata:
        """
        Promove um modelo para PRODUCTION após validação estrita.
        Constitucional: Se a validação falhar, a promoção é BLOQUEADA e o modelo é REJECTED.
        """
        model_dir = self._get_symbol_dir(symbol) / model_id
        meta_file = model_dir / "metadata.json"

        if not meta_file.exists():
            raise FileNotFoundError(f"Metadados do modelo {model_id} não encontrados em {meta_file}")

        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        metadata = ModelMetadata(
            model_id=data["model_id"],
            symbol=data["symbol"],
            engine=data["engine"],
            stage=ModelStage(data["stage"]),
            created_at_utc=data["created_at_utc"],
            sha256_checksum=data["sha256_checksum"],
            hyperparameters=data["hyperparameters"],
            oos_metrics=data["oos_metrics"],
            validation_status=data["validation_status"],
            rejection_reasons=data.get("rejection_reasons", []),
            promoted_at_utc=data.get("promoted_at_utc"),
            rollback_history=data.get("rollback_history", []),
        )

        # Regra 15: Verificação dos portões de qualidade
        rejections: List[str] = []
        if not validation_report.is_approved_for_production:
            rejections.extend(validation_report.rejection_reasons)

        if monte_carlo_report is not None and not monte_carlo_report.is_robust:
            rejections.extend(monte_carlo_report.rejection_reasons)

        if rejections:
            metadata.stage = ModelStage.REJECTED
            metadata.validation_status = "FAILED"
            metadata.rejection_reasons = rejections
            self._save_metadata(model_dir, metadata)
            logger.warning(
                "Promoção para produção REJEITADA pela governança constitucional",
                extra={"model_id": model_id, "reasons": rejections},
            )
            raise PermissionError(
                f"Constitutional Violation: Modelo {model_id} reprovado na validação: {'; '.join(rejections)}"
            )

        # Se aprovado, arquiva o modelo de produção atual se existir
        current_prod = self.get_production_metadata(symbol)
        if current_prod and current_prod.model_id != model_id:
            logger.info(
                "Arquivando modelo de produção anterior",
                extra={"old_prod_id": current_prod.model_id, "new_prod_id": model_id},
            )
            current_prod_dir = self._get_symbol_dir(symbol) / current_prod.model_id
            current_prod.stage = ModelStage.ARCHIVED
            self._save_metadata(current_prod_dir, current_prod)

        # Atualiza métricas OOS e promove o novo modelo
        metadata.stage = ModelStage.PRODUCTION
        metadata.validation_status = "APPROVED"
        metadata.promoted_at_utc = datetime.now(timezone.utc).isoformat()
        metadata.oos_metrics = {
            "mean_profit_factor": validation_report.mean_profit_factor,
            "mean_win_rate": validation_report.mean_win_rate,
            "max_drawdown": validation_report.max_drawdown_observed,
            "total_trades": validation_report.total_oos_trades,
            "mc_prob_of_ruin": monte_carlo_report.probability_of_ruin if monte_carlo_report else None,
            "mc_p99_drawdown": monte_carlo_report.max_drawdown_percentile_99 if monte_carlo_report else None,
        }

        self._save_metadata(model_dir, metadata)

        # Atualiza ponteiro de produção
        prod_pointer_file = self._get_symbol_dir(symbol) / "production_model.json"
        with open(prod_pointer_file, "w", encoding="utf-8") as f:
            json.dump({"production_model_id": model_id, "promoted_at": metadata.promoted_at_utc}, f, indent=2)

        # Limpa cache
        self._cache.pop(symbol.upper(), None)

        logger.info(
            "Modelo PROMOVIDO A PRODUÇÃO com sucesso",
            extra={
                "model_id": model_id,
                "symbol": symbol,
                "profit_factor": validation_report.mean_profit_factor,
            },
        )
        return metadata

    def rollback_production_model(self, symbol: str, reason: str) -> Optional[str]:
        """
        Executa o rollback instantâneo do modelo de produção ativo para a versão
        estável anterior com status ARCHIVED.
        """
        sym = symbol.upper()
        current_prod = self.get_production_metadata(sym)
        if not current_prod:
            logger.warning("Rollback abortado: nenhum modelo ativo em produção para", extra={"symbol": sym})
            return None

        # Procura o modelo arquivado mais recente
        all_models = self.list_models(sym)
        archived_models = [m for m in all_models if m.stage == ModelStage.ARCHIVED]
        if not archived_models:
            logger.error("Rollback impossível: nenhum modelo ARCHIVED anterior encontrado", extra={"symbol": sym})
            return None

        # Ordena pelo horário de promoção mais recente
        sorted_archived = sorted(
            archived_models,
            key=lambda m: m.promoted_at_utc or m.created_at_utc,
            reverse=True,
        )
        target_model = sorted_archived[0]

        # Marca o modelo atual com anomalia como REJECTED
        current_dir = self._get_symbol_dir(sym) / current_prod.model_id
        current_prod.stage = ModelStage.REJECTED
        current_prod.rejection_reasons.append(f"Rollback acionado: {reason}")
        current_prod.rollback_history.append({
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "reverted_to": target_model.model_id,
        })
        self._save_metadata(current_dir, current_prod)

        # Restaura o modelo anterior para PRODUCTION
        target_dir = self._get_symbol_dir(sym) / target_model.model_id
        target_model.stage = ModelStage.PRODUCTION
        target_model.rollback_history.append({
            "restored_at": datetime.now(timezone.utc).isoformat(),
            "restored_from": current_prod.model_id,
            "reason": reason,
        })
        self._save_metadata(target_dir, target_model)

        # Atualiza ponteiro de produção
        prod_pointer_file = self._get_symbol_dir(sym) / "production_model.json"
        with open(prod_pointer_file, "w", encoding="utf-8") as f:
            json.dump({
                "production_model_id": target_model.model_id,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "rollback_note": reason,
            }, f, indent=2)

        self._cache.pop(sym, None)

        logger.warning(
            "ROLLBACK DE MODELO EXECUTADO COM SUCESSO",
            extra={
                "symbol": sym,
                "demoted_model": current_prod.model_id,
                "restored_model": target_model.model_id,
                "reason": reason,
            },
        )
        return target_model.model_id

    def load_production_model(self, symbol: str) -> Optional[Any]:
        """
        Carrega da memória ou disco o modelo ativo em produção após verificar integridade SHA256.
        """
        sym = symbol.upper()
        if sym in self._cache:
            return self._cache[sym]

        metadata = self.get_production_metadata(sym)
        if not metadata:
            return None

        model_file = self._get_symbol_dir(sym) / metadata.model_id / "model.joblib"
        if not model_file.exists():
            logger.error("Arquivo binário do modelo de produção não encontrado", extra={"path": str(model_file)})
            return None

        # Valida integridade do arquivo
        current_checksum = self._calculate_sha256(model_file)
        if current_checksum != metadata.sha256_checksum:
            logger.critical(
                "VIOLAÇÃO DE INTEGRIDADE: Checksum SHA256 divergente do registrado!",
                extra={"expected": metadata.sha256_checksum, "actual": current_checksum},
            )
            raise ValueError(f"Model integrity check failed for {metadata.model_id}")

        loaded_model = joblib.load(model_file)
        self._cache[sym] = loaded_model
        return loaded_model

    def get_production_metadata(self, symbol: str) -> Optional[ModelMetadata]:
        """Recupera os metadados do modelo atualmente ativo em produção."""
        sym = symbol.upper()
        prod_pointer_file = self._get_symbol_dir(sym) / "production_model.json"
        if not prod_pointer_file.exists():
            return None

        with open(prod_pointer_file, "r", encoding="utf-8") as f:
            pointer = json.load(f)

        model_id = pointer.get("production_model_id")
        if not model_id:
            return None

        meta_file = self._get_symbol_dir(sym) / model_id / "metadata.json"
        if not meta_file.exists():
            return None

        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        return ModelMetadata(
            model_id=data["model_id"],
            symbol=data["symbol"],
            engine=data["engine"],
            stage=ModelStage(data["stage"]),
            created_at_utc=data["created_at_utc"],
            sha256_checksum=data["sha256_checksum"],
            hyperparameters=data["hyperparameters"],
            oos_metrics=data["oos_metrics"],
            validation_status=data["validation_status"],
            rejection_reasons=data.get("rejection_reasons", []),
            promoted_at_utc=data.get("promoted_at_utc"),
            rollback_history=data.get("rollback_history", []),
        )

    def list_models(self, symbol: str) -> List[ModelMetadata]:
        """Lista todos os modelos registrados para um símbolo específico."""
        sym_dir = self._get_symbol_dir(symbol)
        models: List[ModelMetadata] = []

        for p in sym_dir.iterdir():
            if p.is_dir():
                meta_file = p / "metadata.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        models.append(
                            ModelMetadata(
                                model_id=data["model_id"],
                                symbol=data["symbol"],
                                engine=data["engine"],
                                stage=ModelStage(data["stage"]),
                                created_at_utc=data["created_at_utc"],
                                sha256_checksum=data["sha256_checksum"],
                                hyperparameters=data["hyperparameters"],
                                oos_metrics=data["oos_metrics"],
                                validation_status=data["validation_status"],
                                rejection_reasons=data.get("rejection_reasons", []),
                                promoted_at_utc=data.get("promoted_at_utc"),
                                rollback_history=data.get("rollback_history", []),
                            )
                        )
                    except Exception as e:
                        logger.warning("Falha ao ler metadata", extra={"path": str(meta_file), "error": str(e)})

        return sorted(models, key=lambda m: m.created_at_utc, reverse=True)

    def _save_metadata(self, model_dir: Path, metadata: ModelMetadata) -> None:
        meta_file = model_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            meta_dict = asdict(metadata)
            meta_dict["stage"] = metadata.stage.value
            json.dump(meta_dict, f, indent=2)


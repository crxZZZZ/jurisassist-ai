"""Text-only ONNX inference, without remote Python code or image dependencies."""

from pathlib import Path

import numpy as np


class E5Encoder:
    def __init__(self, cache_dir: Path):
        import onnxruntime as ort
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
        from tokenizers import Tokenizer

        download_options = {
            "repo_id": "Xenova/multilingual-e5-small",
            "revision": "761b726dd34fb83930e26aab4e9ac3899aa1fa78",
            "cache_dir": cache_dir,
            "allow_patterns": [
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "config.json",
                "onnx/model_quantized.onnx",
            ],
        }
        try:
            root = Path(snapshot_download(**download_options, local_files_only=True))
            if not (root / "onnx/model_quantized.onnx").exists():
                raise LocalEntryNotFoundError("Missing ONNX artifact")
        except LocalEntryNotFoundError:
            root = Path(snapshot_download(**download_options))
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")  # noqa: S106 - tokenizer symbol, not a credential.
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(root / "onnx/model_quantized.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        inputs = {item.name for item in self.session.get_inputs()}
        for offset in range(0, len(texts), 32):
            encodings = self.tokenizer.encode_batch(texts[offset : offset + 32])
            ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
            mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
            batch = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in inputs:
                batch["token_type_ids"] = np.asarray(
                    [e.type_ids for e in encodings], dtype=np.int64
                )
            output = self.session.run(None, batch)[0]
            if output.ndim == 3:
                weights = mask[..., None].astype(np.float32)
                output = (output * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1)
            output = output / np.maximum(np.linalg.norm(output, axis=1, keepdims=True), 1e-12)
            if output.shape[1] != 384:
                raise ValueError("O modelo de embeddings deve gerar 384 dimensões.")
            vectors.extend(output.tolist())
        return vectors

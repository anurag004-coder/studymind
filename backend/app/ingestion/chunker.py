"""Structure-aware chunker per ARCHITECTURE.md §2 and CHALLENGES.md §C."""

import uuid

import tiktoken

from app.ingestion.models import ExtractedBlock, IngestionChunk, ParsedPage


class StructureAwareChunker:
    """Splits parsed pages into grounded, structure-preserving chunks with bounding boxes."""

    def __init__(
        self,
        min_tokens: int = 250,
        max_tokens: int = 500,
        overlap_tokens: int = 50,
        tokenizer_name: str = "cl100k_base",
    ) -> None:
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self._tokenizer: tiktoken.Encoding | None = None
        try:
            self._tokenizer = tiktoken.get_encoding(tokenizer_name)
        except Exception:
            self._tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Counts tokens using tiktoken or fallback whitespace heuristic."""
        if self._tokenizer:
            return len(self._tokenizer.encode(text))
        # Fallback: roughly 1.3 words per token
        return max(1, int(len(text.split()) * 1.3))

    def chunk_pages(
        self,
        pages: list[ParsedPage],
        document_id: str,
        workspace_id: str,
        user_id: str,
        embedding_model: str = "BAAI/bge-m3",
    ) -> list[IngestionChunk]:
        """Processes pages into structured chunks, keeping tables intact and attaching
        section paths."""
        chunks: list[IngestionChunk] = []
        current_section_path: list[str] = []

        # Buffer for accumulating paragraph blocks
        accumulated_blocks: list[ExtractedBlock] = []
        accumulated_tokens = 0
        chunk_index = 0

        def flush_buffer() -> None:
            nonlocal chunk_index, accumulated_blocks, accumulated_tokens
            if not accumulated_blocks:
                return

            chunk_text = "\n\n".join(b.text for b in accumulated_blocks).strip()
            if not chunk_text:
                accumulated_blocks = []
                accumulated_tokens = 0
                return

            p_start = accumulated_blocks[0].page_no
            p_end = accumulated_blocks[-1].page_no
            bboxes = [b.bbox for b in accumulated_blocks]
            section_str = " > ".join(current_section_path) if current_section_path else None

            chunks.append(
                IngestionChunk(
                    chunk_id=str(uuid.uuid4()),
                    document_id=document_id,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    page_start=p_start,
                    page_end=p_end,
                    section_path=section_str,
                    text=chunk_text,
                    token_count=accumulated_tokens,
                    source_type="text",
                    bbox_list=bboxes,
                    chunk_index=chunk_index,
                    embedding_model=embedding_model,
                )
            )
            chunk_index += 1

            # Keep overlap blocks if configured
            if self.overlap_tokens > 0 and len(accumulated_blocks) > 1:
                # Retain the last block as overlap if it doesn't exceed overlap_tokens
                last_block = accumulated_blocks[-1]
                last_tokens = self.count_tokens(last_block.text)
                if last_tokens <= self.overlap_tokens * 1.5:
                    accumulated_blocks = [last_block]
                    accumulated_tokens = last_tokens
                    return

            accumulated_blocks = []
            accumulated_tokens = 0

        for page in pages:
            for block in page.blocks:
                block_tokens = self.count_tokens(block.text)

                # 1. Update section path on headings and flush previous section
                if block.block_type == "heading":
                    if accumulated_tokens > 0:
                        flush_buffer()
                    clean_heading = block.text.strip().splitlines()[0]
                    # Simple 2-level hierarchy: replace or append
                    if len(current_section_path) >= 2:
                        current_section_path = [current_section_path[0], clean_heading]
                    else:
                        current_section_path.append(clean_heading)

                # 2. Table handling: MUST NOT SPLIT TABLES per CHALLENGES.md
                if block.block_type == "table":
                    # Flush previous paragraph buffer first
                    flush_buffer()

                    # Emit table as independent single chunk
                    section_str = " > ".join(current_section_path) if current_section_path else None
                    chunks.append(
                        IngestionChunk(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            workspace_id=workspace_id,
                            user_id=user_id,
                            page_start=block.page_no,
                            page_end=block.page_no,
                            section_path=section_str,
                            text=block.text,
                            token_count=block_tokens,
                            source_type="table",
                            bbox_list=[block.bbox],
                            chunk_index=chunk_index,
                            embedding_model=embedding_model,
                        )
                    )
                    chunk_index += 1
                    continue

                # 3. If adding this block exceeds max_tokens and we already have
                # minimum tokens, flush
                if (
                    accumulated_tokens + block_tokens > self.max_tokens
                    and accumulated_tokens >= self.min_tokens
                ):
                    flush_buffer()

                accumulated_blocks.append(block)
                accumulated_tokens += block_tokens

        # Flush any remaining blocks
        flush_buffer()

        return chunks

"""第5回: ページ単位のベクトル検索。"""

import argparse
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from collections import defaultdict, deque
from pathlib import Path

from google import genai
from google.genai import types
from pydantic_ai.exceptions import ModelHTTPError
import sqlite_vec

from app.config import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MAX_TOKENS, EMBEDDING_MODEL,
    RAG_DB, RAG_DOCUMENT_IDS, RAG_SOURCE, RAG_TOP_K, RAG_TREE, get_api_key,
    RAG_GRAPH, GRAPH_START_K, GRAPH_HOPS, GRAPH_MAX_RESULTS,
)


def get_all_materials() -> str:
    """全資料を、講義・章・ページの情報付きで1つの文字列にまとめる。"""
    documents = json.loads(RAG_SOURCE.read_text(encoding="utf-8"))
    return "\n\n".join(
        f"資料: {document['id']} / {document['title']}\n"
        f"章: {section['section']}\n"
        f"ページ: PDF p.{page['page']} / {page['title']}\n{page['content']}"
        for document in documents
        for section in document["content"]
        for page in section["content"]
    )


def load_pages(source: Path = RAG_SOURCE) -> list[dict]:
    """資料→章→ページのJSONを、対象資料のページ一覧に変換する。"""
    documents = json.loads(source.read_text(encoding="utf-8"))
    pages = []
    for document in documents:
        if document["id"] not in RAG_DOCUMENT_IDS:
            continue
        for section in document["content"]:
            for page in section["content"]:
                pages.append({"page_id": page["id"], "document_id": document["id"],
                              "lecture": int(document["id"][3:5]), "document_title": document["title"],
                              "section": section["section"], "title": page["title"],
                              "page": page["page"], "content": page["content"]})
    return pages


def browse_tree(node_id: str | None = None) -> dict:
    """直下のページは先頭文、指定したページ自身は全文を返す。"""
    tree = json.loads(RAG_TREE.read_text(encoding="utf-8"))
    tree["children"] = [node for node in tree["children"]
                        if node["id"] in RAG_DOCUMENT_IDS]
    node_id = node_id or tree["id"]
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}

    def describe(node, full=False):
        info = {key: node[key] for key in ("id", "kind", "title")}
        if node["kind"] == "page":
            info.update(
                {key: value for key, value in pages[node["id"]].items() if key != "page_id"})
            if not full:
                info["content"] = re.split(
                    r"(?<=[。！？])|\n", info["content"].strip(), maxsplit=1)[0]
        return info

    remaining = [tree]
    while remaining:
        node = remaining.pop()
        if node["id"] == node_id:
            return {
                "node": describe(node, full=True),
                "children": [describe(child) for child in node.get("children", [])],
            }
        remaining.extend(node.get("children", []))
    raise ValueError("対象の目次ノードが見つかりません。")


def read_page(page_id: str) -> dict:
    """第1〜3回の本講義から、指定した1ページの本文と引用情報を返す。"""
    for page in load_pages(RAG_SOURCE):
        if page["page_id"] == page_id:
            return page
    raise ValueError("対象のページが見つかりません。")


def normalized_vector(values: list[float]) -> list[float]:
    """ベクトルの長さを1に揃える。"""
    norm = math.hypot(*values)
    if norm == 0:
        raise ValueError("埋め込みがゼロベクトルです。")
    return [value / norm for value in values]


def embed_text(text: str, task_type: str) -> list[float]:
    """Geminiで文章を埋め込む。入力上限を超えた場合は切り捨てず停止する。"""
    with genai.Client(api_key=get_api_key()) as client:
        count = client.models.count_tokens(
            model=EMBEDDING_MODEL, contents=text).total_tokens
        if count is None or count > EMBEDDING_MAX_TOKENS:
            raise ValueError(f"埋め込み入力が上限を超えるか計測不能です: {count} tokens。")
        response = client.models.embed_content(
            model=EMBEDDING_MODEL, contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=EMBEDDING_DIMENSIONS),
        )
    embedding = response.embeddings[0]
    if embedding.statistics and embedding.statistics.truncated:
        raise ValueError("埋め込みAPIが本文を切り捨てました。")
    return normalized_vector(embedding.values)


@contextmanager
def open_index(path: Path):
    """既存の検索DBを読み取り専用で開き、終了時に閉じる。"""
    if not path.is_file():
        raise FileNotFoundError("検索DBがありません。")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        yield db
    finally:
        db.close()


def search(query: str) -> list[dict]:
    """質問を埋め込み、近いページを最大RAG_TOP_K件返す。"""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("検索語が空です。")
    with open_index(RAG_DB) as db:
        vector = embed_text(query.strip(), "RETRIEVAL_QUERY")
        rows = db.execute("""
            SELECT page_id, document_id, lecture, document_title, section, title, page, content,
                   vec_distance_cosine(embedding, ?) AS distance
            FROM chunks ORDER BY distance, page_id LIMIT ?
        """, (sqlite_vec.serialize_float32(vector), RAG_TOP_K))
        return [dict(row) for row in rows]


def search_graph(query: str) -> dict:
    """ベクトル検索を入口に、前後ページと共通用語で候補を広げる。"""
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}
    graph = json.loads(RAG_GRAPH.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["nodes"]
             if node["kind"] == "term" or node["id"] in pages}
    adjacent = defaultdict(set)
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        if edge["relation"] in ("next_page", "mentions") and a in nodes and b in nodes:
            adjacent[a].add(b)
            adjacent[b].add(a)

    seeds = [hit for hit in search(query) if hit["page_id"] in pages][:min(
        GRAPH_START_K, GRAPH_MAX_RESULTS)]
    seed_ids = {seed["page_id"] for seed in seeds}
    results, candidates = [], {}
    for rank, seed in enumerate(seeds):
        root = seed["page_id"]
        results.append({**pages[root], "distance": seed["distance"], "hops": 0,
                        "path": [{"id": root, "title": pages[root]["title"]}]})
        queue = deque([(root, [root])])
        visited = {root}
        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= GRAPH_HOPS:
                continue
            # 同じ深さなら、接続先が少ない用語からたどる。
            neighbors = sorted(adjacent[current],
                               key=lambda n: (len(adjacent[n]), n))
            for neighbor in neighbors:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                route = path + [neighbor]
                queue.append((neighbor, route))
                if neighbor not in pages or neighbor in seed_ids:
                    continue
                frequency = max(
                    (len(adjacent[n]) for n in route if nodes[n]["kind"] == "term"), default=0)
                priority = (len(route) - 1, frequency, rank, neighbor)
                candidate = {**pages[neighbor], "hops": len(route) - 1,
                             "path": [{"id": n, "title": nodes[n]["title"]} for n in route]}
                if neighbor not in candidates or priority < candidates[neighbor][0]:
                    candidates[neighbor] = (priority, candidate)
    expanded = [candidate for _, candidate in sorted(candidates.values())]
    return {"seeds": results, "expanded": expanded[:max(0, GRAPH_MAX_RESULTS - len(results))],
            "max_hops": GRAPH_HOPS}


def search_tree_graph(query: str, *, candidate_limit: int = 5, max_pages: int = 10) -> dict:
    """Graph候補をTreeの章構成と前後ページで補って返す。"""
    if candidate_limit < 1 or max_pages < 1:
        raise ValueError("候補数とページ数の上限は1以上にしてください。")
    # Graphの候補にはページIDが含まれるため、まずページIDをキーに本文・引用情報を引ける形にする。
    # 同じページIDをTreeの階層とも照合し、GraphとTreeをつなぐ共通キーとして使う。
    pages = {page["page_id"]: page for page in load_pages(RAG_SOURCE)}
    graph = search_graph(query)

    # Treeを走査し、各ページが属する章と章内での順番を索引化する。
    # この位置情報を使い、後で候補ページの前後だけを同じ章から追加できるようにする。
    tree = json.loads(RAG_TREE.read_text(encoding="utf-8"))
    tree["children"] = [node for node in tree.get("children", [])
                        if node["id"] in RAG_DOCUMENT_IDS]
    sections, locations = {}, {}

    def index_tree(node):
        children = node.get("children", [])
        page_children = [child for child in children
                         if child.get("kind") == "page" and child["id"] in pages]
        if page_children:
            section_pages = [pages[child["id"]] for child in page_children]
            sections[node["id"]] = {
                "id": node["id"],
                "title": node["title"],
                "pages": [{"page_id": page["page_id"], "page": page["page"],
                           "title": page["title"]} for page in section_pages],
            }
            for index, page in enumerate(section_pages):
                locations[page["page_id"]] = (node["id"], index)
        for child in children:
            if child.get("kind") != "page":
                index_tree(child)

    index_tree(tree)

    # ベクトル検索で見つけたseedsを先に採用し、その後Graphで広げたexpandedを加える。
    # 対象外のページと重複ページを除き、candidate_limitとmax_pagesの小さい方で候補数を制限する。
    candidates = []
    seen = set()
    for source, retrieval in (("seeds", "seed"), ("expanded", "expanded")):
        for hit in graph.get(source, []):
            page_id = hit.get("page_id")
            if page_id not in pages or page_id in seen:
                continue
            seen.add(page_id)
            candidate = {**pages[page_id], "retrieval": retrieval}
            for key in ("distance", "hops", "path"):
                if key in hit:
                    candidate[key] = hit[key]
            candidates.append(candidate)
            if len(candidates) >= min(candidate_limit, max_pages):
                break
        if len(candidates) >= min(candidate_limit, max_pages):
            break

    result_pages = []
    result_ids = set()
    # Graphの順位を保ったまま候補本文を結果に入れ、Treeで見つけた所属章のIDと見出しを付ける。
    # Tree上の所属先が見つからない候補も、Graphの候補としては残す。
    for candidate in candidates:
        page_id = candidate["page_id"]
        location = locations.get(page_id)
        if location:
            section_id, _ = location
            candidate["section_id"] = section_id
            candidate["section_title"] = sections[section_id]["title"]
        result_pages.append(candidate)
        result_ids.add(page_id)

    # 各Graph候補の直前・直後を、同じ章のページ一覧から追加する。
    # 章をまたいだページは加えず、重複を避けながら本文ページ全体のmax_pagesも守る。
    for candidate in candidates:
        location = locations.get(candidate["page_id"])
        if not location:
            continue
        section_id, index = location
        sibling_pages = sections[section_id]["pages"]
        for neighbor_index in (index - 1, index + 1):
            if neighbor_index < 0 or neighbor_index >= len(sibling_pages):
                continue
            neighbor_id = sibling_pages[neighbor_index]["page_id"]
            if neighbor_id in result_ids or len(result_pages) >= max_pages:
                continue
            result_pages.append({**pages[neighbor_id], "retrieval": "tree_neighbor",
                                 "related_to": candidate["page_id"], "section_id": section_id,
                                 "section_title": sections[section_id]["title"]})
            result_ids.add(neighbor_id)

    relevant_section_ids = {locations[candidate["page_id"]][0]
                            for candidate in candidates if candidate["page_id"] in locations}
    # Graph由来の候補・経路と、Tree由来の章一覧・本文ページを分けて返す。
    # これにより、回答時に候補が見つかった経路と、前後関係を補うために追加したページを区別できる。
    return {
        "graph": {"candidates": [
            {key: candidate[key] for key in ("page_id", "title", "retrieval", "distance", "hops", "path")
             if key in candidate}
            for candidate in candidates
        ]},
        "tree": {
            "sections": [sections[section_id] for section_id in sections
                         if section_id in relevant_section_ids],
            "pages": result_pages,
        },
    }


def run_full_context(agent, question: str, model, instructions: str, prompt_template: str):
    """全資料を一括投入し、検索ツールを使わずに回答する。"""
    prompt = prompt_template.format(
        materials=get_all_materials(), question=question)
    print(f"[full-context] 入力{len(prompt):,}文字")
    try:
        with agent.override(tools=[], instructions=instructions):
            return agent.run_sync(prompt, model=model)
    except ModelHTTPError as e:
        print(f"[full-context] APIエラー HTTP {e.status_code}: {e.body}")
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="エージェントを使わず、講義資料の検索だけを実行する")
    parser.add_argument("query", help="調べたい内容")
    args = parser.parse_args()
    for i, result in enumerate(search(args.query), 1):
        print(f"\n{'=' * 60}\n検索結果 {i}\n{'=' * 60}")
        print(f"講義: {result['document_title']}")
        print(f"章: {result['section']}")
        print(f"タイトル: {result['title']}")
        print(f"ページ: {result['page']}")
        print(f"\n{result['content']}")

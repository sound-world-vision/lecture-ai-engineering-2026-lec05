import json

from app import retrieval


def _hybrid_fixture(tmp_path, monkeypatch):
    pages = [
        {"page_id": f"lec01-main-p00{number}", "document_id": "lec01-main",
         "lecture": 1, "document_title": "講義1", "section": section,
         "title": f"ページ{number}", "page": number, "content": f"本文{number}"}
        for number, section in ((1, "章A"), (2, "章A"), (3, "章B"),
                                (4, "章B"), (5, "章B"))
    ]
    tree = {
        "id": "root", "kind": "collection", "title": "資料", "children": [{
            "id": "lec01-main", "kind": "document", "title": "講義1", "children": [
                {"id": "lec01-main-s001", "kind": "section", "title": "章A",
                 "children": [{"id": page["page_id"], "kind": "page", "title": page["title"]}
                              for page in pages[:2]]},
                {"id": "lec01-main-s003", "kind": "section", "title": "章B",
                 "children": [{"id": page["page_id"], "kind": "page", "title": page["title"]}
                              for page in pages[2:]]},
            ],
        }],
    }
    tree_path = tmp_path / "tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")
    graph = {
        "seeds": [{**pages[1], "distance": 0.1, "hops": 0, "path": []}],
        "expanded": [{**pages[3], "hops": 2, "path": []},
                     {**pages[1], "hops": 1, "path": []}],
    }
    monkeypatch.setattr(retrieval, "RAG_TREE", tree_path)
    monkeypatch.setattr(retrieval, "load_pages", lambda _source: pages)
    monkeypatch.setattr(retrieval, "search_graph", lambda _query: graph)


def test_search_tree_graph_adds_unique_neighbors_within_their_section(tmp_path, monkeypatch):
    _hybrid_fixture(tmp_path, monkeypatch)

    result = retrieval.search_tree_graph("比較質問")

    pages = result["tree"]["pages"]
    page_ids = [page["page_id"] for page in pages]
    assert page_ids == [
        "lec01-main-p002", "lec01-main-p004", "lec01-main-p001",
        "lec01-main-p003", "lec01-main-p005",
    ]
    assert len(page_ids) == len(set(page_ids))
    assert [page["retrieval"] for page in pages] == [
        "seed", "expanded", "tree_neighbor", "tree_neighbor", "tree_neighbor",
    ]
    assert {section["title"]
            for section in result["tree"]["sections"]} == {"章A", "章B"}


def test_search_tree_graph_respects_page_limit(tmp_path, monkeypatch):
    _hybrid_fixture(tmp_path, monkeypatch)

    result = retrieval.search_tree_graph("比較質問", max_pages=4)

    assert len(result["tree"]["pages"]) == 4
    assert "lec01-main-p005" not in {page["page_id"]
                                     for page in result["tree"]["pages"]}

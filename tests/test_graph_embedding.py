import uuid

import numpy as np

from dau_archive import embedding_jobs, embeddings, graph, search
from dau_archive.db import connect, init_db


def _document(db, title, owner, department, visibility, words):
    doc_id, version_id, chunk_id = (str(uuid.uuid4()) for _ in range(3))
    db.execute("INSERT INTO documents(id,kind,title,department,visibility,owner_id,current_version_id) "
               "VALUES (?,'iso',?,?,?,?,?)",
               (doc_id, title, department, visibility, owner, version_id))
    db.execute("INSERT INTO versions(id,document_id,version_no,filename,mime_type,sha256,blob_name,"
               "status,created_by) VALUES (?,?,1,'file.txt','text/plain','sha','blob','ready',?)",
               (version_id, doc_id, owner))
    db.execute("INSERT INTO chunks(id,version_id,page_no,ordinal,text) VALUES (?,?,1,0,?)",
               (chunk_id, version_id, words))
    db.execute("INSERT INTO chunks_fts(text,chunk_id) VALUES (?,?)", (words, chunk_id))
    return doc_id, chunk_id


def test_graph_acl_depth_and_relation_review(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    init_db()
    with connect() as db:
        db.executemany("INSERT INTO users(id,username,password_hash,role,department) "
                       "VALUES (?,?, 'hash','staff',?)",
                       [('a', 'alice', 'Văn thư'), ('b', 'bob', 'Đào tạo')])
        first, _ = _document(db, 'Quy trình', 'a', 'Văn thư', 'restricted', 'lưu trữ hồ sơ')
        second, _ = _document(db, 'Biểu mẫu', 'a', 'Văn thư', 'department', 'lưu trữ biểu mẫu')
        hidden, _ = _document(db, 'Hồ sơ kín', 'b', 'Đào tạo', 'restricted', 'thông tin kín')
        db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,status) "
                   "VALUES ('r1',?,?,'in_file','confirmed')", (first, second))
        db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,status) "
                   "VALUES ('r2',?,?,'related','proposed')", (second, hidden))
    alice = {'id': 'a', 'role': 'staff', 'department': 'Văn thư'}
    bob = {'id': 'b', 'role': 'staff', 'department': 'Đào tạo'}
    result = graph.neighborhood(alice, first, depth=3)
    assert {node['id'] for node in result['nodes']} == {first, second}
    assert [edge['id'] for edge in result['edges']] == ['r1']
    assert graph.neighborhood(bob, first) is None
    with connect() as db:
        db.execute("INSERT INTO grants(document_id,user_id) VALUES (?,?)", (first, 'b'))
        db.execute("INSERT INTO grants(document_id,user_id) VALUES (?,?)", (second, 'b'))
    result = graph.neighborhood(bob, first, depth=3, include_proposed=False)
    assert {edge['id'] for edge in result['edges']} == {'r1'}
    result = graph.neighborhood(bob, first, depth=3, include_proposed=True)
    assert {edge['id'] for edge in result['edges']} == {'r1', 'r2'}


def test_model_specific_vectors_search_and_similarity(monkeypatch, tmp_path):
    monkeypatch.setenv("DAU_DATA_DIR", str(tmp_path))
    init_db()
    with connect() as db:
        db.executemany("INSERT INTO users(id,username,password_hash,role,department) "
                       "VALUES (?,?, 'hash','staff',?)",
                       [('a', 'alice', 'Văn thư'), ('b', 'bob', 'Đào tạo')])
        root, root_chunk = _document(db, 'Quy trình nhập', 'a', 'Văn thư', 'department', 'quy trình nhập hồ sơ')
        peer, peer_chunk = _document(db, 'Quy trình lưu', 'a', 'Văn thư', 'department', 'quy trình lưu hồ sơ')
        hidden, hidden_chunk = _document(db, 'Tài liệu kín', 'b', 'Đào tạo', 'restricted', 'bí mật hồ sơ')
    model = embeddings.model_id()
    vectors = {root_chunk: [1., 0.], peer_chunk: [.8, .6], hidden_chunk: [1., 0.]}
    with connect() as db:
        for chunk_id, values in vectors.items():
            db.execute("INSERT INTO chunk_embeddings(chunk_id,model_id,embedding) VALUES (?,?,?)",
                       (chunk_id, model, np.asarray(values, dtype='<f4').tobytes()))
    for document_id in (root, peer, hidden):
        embedding_jobs._refresh_document_embedding(document_id, model)
    user = {'id': 'a', 'role': 'staff', 'department': 'Văn thư'}
    monkeypatch.setattr(search, 'available', lambda: True)
    monkeypatch.setattr(search, 'embed_query', lambda q: np.asarray([1., 0.], dtype='<f4'))
    result = search.search(user, 'lưu hồ sơ', mode='hybrid')
    assert result['effective_mode'] == 'hybrid'
    assert hidden not in {item['document_id'] for item in result['results']}
    result = search.search(user, 'không có từ này', mode='semantic')
    assert {item['document_id'] for item in result['results']} == {root, peer}
    similar = embedding_jobs.similar_documents(user, root)
    assert [item['id'] for item in similar['results']] == [peer]
    embeddings.select_model('bge-m3')
    assert embedding_jobs.similar_documents(user, root)['indexed'] is False
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM chunk_embeddings WHERE model_id=?', (model,)).fetchone()[0] == 3

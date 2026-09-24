"""Reproducible bilingual retrieval smoke benchmark; does not touch Chroma/SQLite.

Run with embedding environment variables to compare providers. Exit 1 means
one language missed the 11/12 top-five gate. This small demo is not a production eval.
"""
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from backend.app.embeddings import get_embeddings
from backend.scripts.generate_demo_corpus import CORPUS

CASES = [
    ('Nghỉ phép', 'Tôi được nghỉ phép bao nhiêu ngày mỗi năm?', 'How many annual leave days do I get?'),
    ('WFH', 'Mỗi tuần được làm việc ở nhà mấy ngày?', 'How many days per week can I work from home?'),
    ('OT', 'Làm thêm vào ngày lễ được trả bao nhiêu?', 'What is the overtime pay rate on public holidays?'),
    ('Chấm công', 'Khi nào bảng công hàng tháng bị khóa?', 'When does the monthly attendance record close?'),
    ('Quy định thử việc', 'Thời gian thử việc kéo dài bao lâu?', 'How long is the probation period?'),
    ('Quy trình nghỉ việc', 'Muốn thôi việc thì phải báo trước bao lâu?', 'How much notice must I give before resigning?'),
    ('Quy trình thanh toán', 'Kế toán thanh toán vào thứ mấy?', 'On which weekday does accounting process payments?'),
    ('Công tác phí', 'Đi công tác về thì hạn nộp hóa đơn hoàn tiền là bao lâu?', 'How soon after a business trip must I submit expenses?'),
    ('Đặt phòng họp', 'Tôi muốn đặt phòng để họp nhóm thì làm thế nào?', 'How do I reserve a meeting room?'),
    ('Mượn thiết bị', 'Tôi cần mượn máy chiếu thì liên hệ ai?', 'Who should I contact to borrow a projector?'),
    ('Thưởng', 'Lương tháng thứ mười ba được trả khi nào?', 'When is the thirteenth month salary paid?'),
    ('Bảo hiểm', 'Người phụ thuộc có được đăng ký bảo hiểm sức khỏe không?', 'Can dependents enroll in health insurance?'),
]


def main():
    embedding = get_embeddings()
    entries = [dict(e, category=k) for k, group in CORPUS.items() for e in group]
    texts = ['Nhóm tài liệu: '+e['category']+'\n'+'\n'.join(e['paragraphs']) for e in entries]
    def vectors(texts, query=False):
        v = np.asarray(embedding.encode(texts, query=query))
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    documents = vectors(texts)
    result = {'provider': embedding.provider, 'model': embedding.model_name, 'corpus_size': len(entries), 'results': {}}
    for language in ['vi', 'vi_no_accents', 'en']:
        queries = [c[2] if language == 'en' else c[1] for c in CASES]
        if language == 'vi_no_accents':
            queries = [''.join(ch for ch in unicodedata.normalize('NFD', q) if unicodedata.category(ch) != 'Mn').replace('đ', 'd') for q in queries]
        rows = []
        for case, scores in zip(CASES, vectors(queries, query=True) @ documents.T):
            order = np.argsort(-scores).tolist()
            target = next(i for i, entry in enumerate(entries) if entry['topic'] == case[0])
            rows.append({'topic': case[0], 'rank': order.index(target)+1, 'top1': entries[order[0]]['topic']})
        result['results'][language] = {'top1': sum(r['rank'] == 1 for r in rows), 'top5': sum(r['rank'] <= 5 for r in rows), 'total': len(rows), 'details': rows}
    result['passed'] = all(r['top5'] >= 11 for r in result['results'].values())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

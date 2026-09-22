# Knowledge Taxonomy

The corpus the assistant consumes, as provided by the business. Each topic
becomes one document ingested via `POST /documents/upload` (admin selects the
permitted roles). Role mapping below is the suggested default — the admin can
override it per upload.

## Categories

### Policy

| Topic (document)                  | Suggested visibility | Note                              |
| --------------------------------- | -------------------- | --------------------------------- |
| Nghỉ phép                         | all roles            |                                   |
| Đi muộn/về sớm                    | all roles            |                                   |
| Chấm công                         | all roles            |                                   |
| WFH                               | all roles            |                                   |
| OT                                | all roles            |                                   |
| Chính sách phúc lợi               | hr, manager          | compensation-sensitive            |
| Bảo hiểm                          | hr, manager          | compensation-sensitive            |
| Thưởng                            | hr, manager          | compensation-sensitive            |
| Quy định thử việc                 | all roles            |                                   |
| Quy trình nghỉ việc               | all roles            |                                   |
| Quy trình onboarding              | all roles            |                                   |
| Chính sách đào tạo                | all roles            |                                   |

### Operations

| Topic (document)                  | Suggested visibility |
| --------------------------------- | -------------------- |
| Quy trình xin mua hàng            | all roles            |
| Quy trình thanh toán              | all roles            |
| Công tác phí                      | all roles            |
| Mượn thiết bị                     | all roles            |
| Đặt phòng họp                     | all roles            |
| Quy trình approval                | all roles            |
| Quy định sử dụng tài sản          | all roles            |

### Company tour

| Topic (document)                  | Suggested visibility |
| --------------------------------- | -------------------- |
| Company handbook                  | all roles            |
| Văn hóa                           | all roles            |
| Giá trị công ty                   | all roles            |
| Cơ cấu tổ chức                    | all roles            |
| Các phòng ban                     | all roles            |
| Quy định nội bộ                   | all roles            |
| Event                             | all roles            |
| Teambuilding                      | all roles            |
| Sinh nhật                         | all roles            |
| Chính sách employee benefit       | all roles            |

### Contact

| Topic (document) | Suggested visibility |
| ---------------- | -------------------- |
| Contact liên hệ  | all roles            |

## Design notes

- **Contact → fallback (FR07):** the Contact document is the source for the
  fallback answer. When retrieval finds no authorized evidence for a question,
  the assistant must not invent content — it points the user to the matching
  contact email (HR for policy/payroll questions, IT for accounts/devices,
  Operations for purchasing/payment).
- **Sensitive trio** (`Chính sách phúc lợi`, `Bảo hiểm`, `Thưởng`) demonstrates
  role isolation: an employee asking about them gets the fallback contact
  instead of HR-only content (useful demo for T22 security testing).
- **Vietnamese content:** prefer DOCX ingestion. python-docx extracts Unicode
  natively; PDFs only extract Vietnamese correctly when they carry proper
  Unicode font maps (scanned or WinAnsi-only PDFs will produce garbage and are
  rejected with `422` when no text is extractable).
- **Chunking:** chunks are sized in whitespace-separated tokens (~400 with
  50-token overlap), which behaves well for Vietnamese (space-separated
  syllables). Each chunk inherits the document's role flags (§3.2).

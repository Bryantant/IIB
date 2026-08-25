## > Ringkasan

**Job Order Corrugator Receipt** (kode dokumen: `IBJOP1{YY}{NNNNN}`, sering disingkat **JOP1 Receipt**) adalah dokumen custom di sistem ERP (module IIB) yang mencatat **hasil produksi aktual** tahap corrugator terhadap sebuah **Job Order Corrugator** yang sudah submitted — berapa qty yang benar-benar dihasilkan dan masuk ke gudang.

Berbeda dari Job Order Corrugator (yang hanya "perintah kerja"), dokumen ini adalah **transaksi stok & akuntansi sesungguhnya**: begitu di-submit, sistem membuat **Stock Ledger Entry** (menambah stok di warehouse tujuan) dan **GL Entry** (jurnal Debit-stok / Kredit-expense) — mewarisi behavior dari `StockController` bawaan ERPNext, mirip Stock Entry / Purchase Receipt.

Dokumen ini bersifat **submittable** (draft → submitted → cancelled).

---

## > Kapan Digunakan

Gunakan Job Order Corrugator Receipt setiap kali hasil produksi corrugator dari sebuah Job Order Corrugator (JO P1) yang sudah submitted **fisiknya sudah jadi dan diterima** — baik seluruh qty sekaligus, maupun bertahap (partial). Satu JO Corrugator boleh punya **banyak Receipt** (untuk penerimaan bertahap), dan satu Receipt boleh berisi baris dari **beberapa JO Corrugator sekaligus**.

---

## > Alur Kerja

### > 1. Isi Header

| Field | Keterangan |
| --- | --- |
| **Company** | Default: PT. Interpak Industries Batam (tersembunyi di form) |
| **Date** (posting_date) | Default hari ini. **Read-only** kecuali checkbox **Edit Posting Date and Time** dicentang (lihat baris berikutnya) |
| **Posting Time** | Default waktu saat ini. **Read-only** kecuali checkbox **Edit Posting Date and Time** dicentang |
| **Edit Posting Date and Time** | Checkbox, hanya muncul selagi dokumen masih draft. Sama seperti Sales Invoice/Purchase Invoice/Delivery Note di ERPNext: **tidak dicentang** (default) → Date & Posting Time terkunci (read-only di form) dan otomatis di-set ke tanggal/jam saat ini setiap kali disimpan. **Dicentang** → keduanya bisa diedit manual dan nilai yang diisi user dipertahankan |
| **Received By** | Wajib diisi (nama/identitas penerima barang) |
| **Notes** | Catatan bebas (opsional) — juga dipakai sebagai remarks default di GL Entry kalau diisi |
| **Expense Account** | Wajib. Harus akun **leaf** (bukan group), dan kalau Company sudah diisi harus milik company yang sama. Auto-terisi dari **IIB Settings** (`default_expense_account`) saat dokumen baru dibuat |
| **Cost Center** | Wajib. Auto-terisi dari **IIB Settings** (`default_cost_center`), atau fallback ke Cost Center default Company kalau setting tidak diisi |

### > 2. Isi Tabel "Items"

Ada 2 cara mengisi baris item:

**A. Manual** — alur: pilih **JO No** dulu → lalu pilih **Item Code**.
1. **JO No** — hanya menampilkan Job Order Corrugator yang **submitted** dan belum Completed/Closed/Cancelled (sama seperti filter di dialog picker B).
2. **Item Code** — begitu JO No dipilih, daftar pilihannya otomatis terbatas hanya ke item yang ada di JO Corrugator tersebut **dan** masih punya sisa qty pending (belum diterima penuh). **Kalau JO No belum diisi, daftar pilihan Item Code kosong** — user wajib pilih JO No dulu sebelum bisa memilih Item Code.
3. Begitu Item Code dipilih, field lain **auto-fill**: Item Name/Description/Quality/Flute/Width/Length/Creasing/UOM/Basic Rate ditarik dari Item Master (fetch otomatis bawaan field), sedangkan SO No/Due Date/Delivery Date/Quantity (default ke sisa qty pending) serta `job_order_corrugator_item` (referensi baris JO Corrugator yang dipakai untuk validasi) diambil dari baris Job Order Corrugator Item yang cocok.
4. Mengganti JO No pada baris yang sudah terisi akan mengosongkan kembali Item Code & `job_order_corrugator_item` baris itu (supaya filter & auto-fill tidak nyasar ke JO lama).

**B. Tombol "Get Items From → Job Order Corrugator"** (hanya muncul saat dokumen masih draft) — membuka dialog 2 langkah:
1. **MultiSelectDialog** memilih 1 atau lebih Job Order Corrugator (submitted, status belum Completed/Closed/Cancelled), dengan opsi filter Customer/Tanggal, dan checkbox **"Select Job Order Corrugator Item"** (aktif default) untuk memilih baris item spesifik, bukan seluruh JO Corrugator.
2. Sistem menambahkan seluruh baris **pending** (qty yang belum diterima) dari JO Corrugator terpilih ke tabel Items, lengkap dengan qty = sisa pending, Due Date, Delivery Date, dan Target Warehouse otomatis. Kalau tidak ada baris pending sama sekali, sistem menampilkan pesan "No pending items found..." dan tidak menambahkan apa pun.

> Kedua cara ini bisa dicampur bebas dalam satu dokumen — baris hasil picker dan baris yang diisi manual sama-sama tervalidasi dengan aturan yang sama saat submit (lihat [Validasi](#validasi)).

| Field | Keterangan |
| --- | --- |
| **JO No** (job_order_corrugator) | Bisa diisi manual (Link, difilter ke JO Corrugator yang masih terbuka) atau otomatis lewat picker |
| **Corrugator Item Row** (job_order_corrugator_item) | Read-only — diisi otomatis begitu Item Code dipilih (jalur manual) atau oleh picker; dipakai untuk validasi qty & sinkronisasi received_qty |
| **Item Code**, **Item Name**, **Description** | Item Code bisa diisi manual (difilter ke item di JO No terpilih) atau lewat picker; Item Name & Description read-only, ditarik dari Item Master |
| **Quality**, **Flute**, **Width**, **Length**, **Creasing** | Read-only, ikut ditarik dari Item Master (`item_code.custom_board_quality`/`custom_flute`/`custom_width`/`custom_length`/`custom_crease_w`) — nilai yang sama persis dengan yang tampil di baris Job Order Corrugator sumbernya (lihat [Catatan Teknis](#catatan-teknis-untuk-tim-itdeveloper)) |
| **SO No** (sales_order) | Read-only, referensi Sales Order (untuk keterlacakan) — terisi dari baris JO Corrugator Item yang cocok |
| **Due Date**, **Delivery Date** | Read-only, ditarik dari baris JO Corrugator sumber |
| **Basic Rate** | Ditarik otomatis dari `valuation_rate` Item (hanya kalau kosong — `fetch_if_empty`), bisa diedit manual. Tidak boleh negatif |
| **Quantity** | Jumlah aktual yang diterima. Wajib > 0. Untuk baris manual, default terisi ke sisa qty pending JO Corrugator Item yang cocok — bisa diubah user |
| **UOM** | Read-only, mengikuti Stock UOM item — **tidak mendukung konversi UOM** |
| **Target Warehouse** | Tersembunyi di form, terkunci ke `"Raw Material - IIB"` |
| **Amount** | Read-only, selalu **0** — Basic Rate saat ini murni informasi/referensi, **tidak** mempengaruhi nilai stok/GL (lihat [Catatan Teknis](#catatan-teknis-untuk-tim-itdeveloper)) |

### > 3. Submit

Saat tombol **Submit** ditekan, sistem menjalankan validasi (lihat bagian berikut), lalu:

1. Membuat **Stock Ledger Entry** — menambah qty di Target Warehouse (`Raw Material - IIB`) untuk tiap baris
2. Membuat **GL Entry** seimbang: Debit akun stok warehouse tujuan, Kredit **Expense Account** header (nilai amount = 0 untuk seluruh baris — lihat catatan di atas)
3. Menghitung ulang `received_qty` / `pending_qty` di JO Corrugator sumber, dan memperbarui status header JO Corrugator (`To Receive` → `Partially Received`/`Completed`)
4. Mencatat nomor Receipt ini ke field `created_receipts` pada JO Corrugator sumber (dipisah koma kalau lebih dari satu)
5. Status header Receipt di-set ke **"Submitted"**

---

## > Validasi

### > Item & UOM

- Tabel Items tidak boleh kosong
- Tiap baris: Item Code wajib, harus stock item, harus punya Stock UOM, dan UOM baris **harus sama** dengan Stock UOM item (tidak ada konversi)
- Qty harus > 0, Basic Rate tidak boleh negatif, Target Warehouse wajib terisi

### > Konsistensi dengan Baris JO Corrugator Sumber (`job_order_corrugator_item`)

Kalau baris Receipt terhubung ke sebuah baris JO Corrugator (lewat picker, biasanya selalu terhubung):

- Baris JO Corrugator tersebut harus benar-benar ada
- Kalau `job_order_corrugator` (header) juga diisi, harus konsisten — baris JO Corrugator itu harus benar milik JO Corrugator header tersebut
- **Item Code** dan **UOM** baris Receipt harus **persis sama** dengan baris JO Corrugator sumbernya

Selain itu, JO Corrugator yang direferensikan (`job_order_corrugator` di baris) harus **sudah submitted** — kalau masih draft, ditolak.

### > Expense Account

- Harus ada, harus akun leaf (bukan group), dan kalau Company diisi harus satu company dengan Expense Account

### > Guard Over-Receipt vs Toleransi (`validate_receipt_qty_vs_corrugator`)

Ini validasi inti dokumen ini — mencegah menerima lebih banyak dari yang di-order di JO Corrugator (plus toleransi yang dikonfigurasi):

1. Baris-baris di **Receipt ini** dijumlahkan per `job_order_corrugator_item` (kalau ada baris duplikat untuk row yang sama, dijumlah dulu).
2. Untuk tiap baris JO Corrugator yang tersentuh, sistem membaca **qty yang di-order** (`qty`) dan **qty yang sudah diterima dari Receipt lain yang submitted** (`received_qty` — field ini hanya mengikuti Receipt submitted, jadi draft yang sedang disimpan/submit sendiri tidak pernah menghitung dirinya dua kali).
3. Toleransi diambil dari tabel yang sama dengan JO Corrugator (**IIB Settings Corrugator Tolerance**) lewat helper bersama `lookup_tolerance`.
4. Kalau `qty sudah diterima + qty di receipt ini > qty di-order + toleransi` → **ditolak**, pesan error menyebutkan JO Corrugator, Item, qty yang diminta, total yang akan jadi, batas maksimum, dan **sisa maksimum yang masih bisa diterima saat ini**.

Baris tanpa `job_order_corrugator_item` (jarang terjadi, biasanya kalau ditambah manual tanpa lewat picker) **dilewati** dari pengecekan ini secara diam-diam.

---

## > Pembatalan (Cancel)

Saat Receipt di-cancel:

- Stock Ledger Entry dan GL Entry yang tadi dibuat **dibalik** (reverse), memakai perilaku standar `StockController` — `GL Entry` dan `Stock Ledger Entry` dikecualikan dari pengecekan "linked doctype blocks cancel" bawaan Frappe supaya proses reversal ini bisa jalan
- `received_qty`/`pending_qty` di JO Corrugator sumber dihitung ulang (otomatis turun karena Receipt ini sudah tidak lagi dihitung "submitted"), dan status header JO Corrugator ikut disesuaikan ulang (bisa turun dari Completed kembali ke Partially Received, dst — kecuali JO Corrugator berstatus Closed/Cancelled, yang tidak pernah ditimpa otomatis)
- Nomor Receipt ini **dihapus** dari daftar `created_receipts` pada JO Corrugator sumber
- Status header Receipt di-set ke **"Cancelled"**

> Membatalkan JO Corrugator sumbernya sendiri **ditolak** kalau masih ada Receipt yang submitted menunjuk ke dia — lihat `job_order_corrugator.md` bagian Pembatalan. Urutan yang benar: cancel Receipt dulu, baru cancel JO Corrugator.

---

## > Penomoran Dokumen

Nomor Job Order Corrugator Receipt dibuat otomatis dengan format **`IBJOP1{YY}{NNNNN}`**, contoh: `IBJOP126000001` — perhatikan prefix `IBJOP1` (bukan `IIB`) diikuti tahun lalu 5 digit nomor urut.

- `YY` = 2 digit tahun sesuai **Date** (posting_date)
- `NNNNN` = nomor urut 5 digit, reset ke 1 setiap pergantian tahun
- Diatur lewat singleton **IIB Document Naming Settings** (counter key: `jop1r`)

---

## > Error Umum & Penyebabnya

| Pesan Error | Penyebab | Solusi |
| --- | --- | --- |
| "Expense Account ... does not exist" | Expense Account yang diisi tidak valid | Pilih akun yang benar-benar ada |
| "Expense Account ... must be a leaf account, not a group account" | Expense Account yang dipilih adalah akun group | Pilih akun leaf (non-group) |
| "Expense Account ... does not belong to company ..." | Expense Account beda company dari header | Sesuaikan Expense Account atau Company |
| "Items table is empty" | Submit/save tanpa baris item | Tambahkan minimal 1 baris, biasanya lewat "Get Items From → Job Order Corrugator" |
| "Row ...: Item Code is required" / "Item ... not found" | Item Code kosong atau tidak valid | Isi/perbaiki Item Code |
| "Row ...: Item ... must be a stock item for Job Order Corrugator Receipt" | Item Code bukan stock item | Pakai item yang berstatus stock item |
| "Row ...: Item ... must use stock UOM ...; current UOM is ..." | UOM baris tidak sama dengan Stock UOM item | Kosongkan UOM agar terisi ulang otomatis, atau perbaiki data item |
| "Row ...: Quantity must be positive" | Qty diisi 0 atau negatif | Isi qty > 0 |
| "Row ...: Target Warehouse is required" | Target Warehouse kosong (harusnya otomatis terisi) | Pilih ulang item lewat picker, atau isi manual ke `Raw Material - IIB` |
| "Row ...: Basic Rate cannot be negative" | Basic Rate diisi negatif | Perbaiki nilai Basic Rate |
| "Row ...: Job Order Corrugator ... is not submitted" | JO Corrugator sumber baris ini masih draft | Submit dulu JO Corrugator-nya sebelum membuat Receipt |
| "Row ...: Job Order Corrugator Item ... not found" | `job_order_corrugator_item` yang terhubung sudah tidak ada (baris JO Corrugator dihapus) | Hapus baris ini, ambil ulang lewat "Get Items From" |
| "Row ...: Job Order Corrugator Item ... does not belong to ..." | Baris JO Corrugator sumber ternyata bukan milik `job_order_corrugator` header yang diisi | Perbaiki referensi, atau kosongkan & ambil ulang lewat picker |
| "Row ...: Item Code must match linked Job Order Corrugator Item ..." | Item Code diubah manual sehingga tidak lagi sama dengan baris JO Corrugator sumber | Jangan ubah Item Code baris yang sudah terhubung ke JO Corrugator; hapus & tambah ulang kalau item-nya memang salah |
| "Row ...: UOM must match linked Job Order Corrugator Item ..." | UOM tidak sinkron dengan baris JO Corrugator sumber | Sama seperti di atas — jangan ubah manual, ambil ulang lewat picker |
| "JO P1 ... — Item ...: receipt qty ... would bring total received to ..., exceeding ordered qty ... + tolerance ... = .... Maximum receivable now: ..." | Total qty yang diterima (Receipt ini + Receipt submitted sebelumnya) melebihi qty di-order + toleransi di JO Corrugator | Kurangi qty baris ini ke batas "Maximum receivable" yang disebutkan di pesan error, atau buat JO Corrugator tambahan kalau memang perlu menerima lebih banyak |

---

## > Dokumen Terkait (Doctype)

- **Job Order Corrugator Receipt Item** — child table baris item pada Receipt
- **Job Order Corrugator** / **Job Order Corrugator Item** — dokumen & baris sumber; lihat [`job_order_corrugator.md`](job_order_corrugator.md)
- **IIB Settings** — sumber default Expense Account & Cost Center, serta tabel toleransi (`IIB Settings Corrugator Tolerance`, dipakai bersama dengan JO Corrugator)
- **Stock Ledger Entry** / **GL Entry** — dibuat otomatis lewat `StockController` bawaan ERPNext saat submit, dibalik saat cancel

---

## > Catatan Teknis (untuk tim IT/Developer)

- Lokasi kode: `iib/iib/doctype/job_order_corrugator_receipt/job_order_corrugator_receipt.py`, client script: `job_order_corrugator_receipt.js`
- Class `JobOrderCorrugatorReceipt` meng-*extend* `erpnext.controllers.stock_controller.StockController` (bukan `frappe.model.document.Document` biasa) supaya bisa memakai infrastruktur Stock Ledger Entry & GL Entry bawaan ERPNext (`get_sl_entries`, `get_gl_dict`, `make_gl_entries`, `make_gl_entries_on_cancel`)
- `make_sl_entries` di-override untuk **skip** `update_batch_qty` — child table `items` dokumen ini tidak punya kolom `serial_and_batch_bundle` yang dipakai standar Frappe untuk itu (meskipun field `serial_and_batch_bundle` ada di JSON, ia tersembunyi & tidak dipakai aktif)
- **Edit Posting Date and Time**: karena meng-*extend* `StockController` → `AccountsController` → `erpnext.utilities.transaction_base.TransactionBase`, doctype ini otomatis mewarisi method `validate_posting_time()` — tinggal dipanggil di awal `validate()` (persis pola Sales Invoice/Purchase Invoice/Delivery Note, tidak perlu logic custom). Server memaksa reset ke waktu sekarang saat checkbox off; client script (`job_order_corrugator_receipt.js`, handler `set_posting_date_and_time_read_only`) mengunci field `posting_date`/`posting_time` jadi read-only di form untuk kondisi yang sama — meniru `erpnext.stock.StockController.setup_posting_date_time_check()` di JS core ERPNext
- **Amount selalu 0** by design saat ini — baik di server (`validate_items` men-set `row.amount = 0` secara eksplisit) maupun client (`recompute_totals` di JS juga memaksa 0). GL Entry yang dibuat karenanya berjumlah Rp 0 tapi tetap dicatat (untuk keterlacakan/audit trail warehouse movement), bukan untuk valuasi. Kalau ke depan valuasi ingin diaktifkan, `basic_rate × qty` sudah tersedia sebagai basis perhitungan tapi belum dipakai
- Toleransi dibaca lewat helper bersama `iib.iib.utils.tolerance.lookup_tolerance` (sama persis dengan yang dipakai Job Order Corrugator) — logic-nya sengaja diisolasi ke method `_get_corrugator_tolerance_rows()` dan `_get_corrugator_item_data()` supaya bisa di-*override*/stub di unit test tanpa perlu koneksi DB Frappe live
- **Quality / Flute / Width / Length / Creasing** (fieldname `quality`, `flute`, `width`, `length`, `creasing`) di-*fetch* lewat `fetch_from item_code.custom_*` — sama seperti pola board spec di **Job Order Corrugator Item**. `creasing` khusus hanya mengambil `custom_crease_w` (bukan gabungan Crease W + Crease L). Karena baris yang ditambahkan lewat dialog "Get Items From → Job Order Corrugator" di-assign langsung (`row.xxx = ...`, bukan lewat `frappe.model.set_value`), `fetch_from` tidak otomatis terpicu untuk baris tersebut — endpoint `get_corrugator_items_for_receipt_dialog` karena itu ikut mengembalikan `quality`/`flute`/`width`/`length`/`crease_w` yang sudah tersimpan di baris **Job Order Corrugator Item** sumber, dan `job_order_corrugator_receipt.js` meng-assign-nya langsung ke baris baru. Untuk baris yang diisi manual (Item Code dipilih langsung di grid), `fetch_from` jalan seperti biasa
- **Pemilihan manual JO No/Item Code** (dikembalikan setelah sempat dikunci read-only-picker-saja): field `job_order_corrugator` dan `item_code` di child table **bukan lagi read-only**. `job_order_corrugator` difilter lewat `frm.set_query` di `setup()` (docstatus=1, status belum Completed/Closed/Cancelled — sama seperti filter picker). `item_code` difilter dinamis per-baris lewat `frm.set_query` di `onload_post_render` yang selalu memanggil custom search query `get_corrugator_component_items` — endpoint ini mengembalikan list kosong kalau `job_order_corrugator` baris itu belum diisi, sehingga Item Code memang tidak punya opsi apa pun sampai JO No dipilih dulu (bukan fallback ke filter Component/stock item generik). Field non-`fetch_from` (SO No/Due Date/Delivery Date/Quantity default/`job_order_corrugator_item`) diisi lewat handler `item_code` di `frappe.ui.form.on("Job Order Corrugator Receipt Item", ...)` yang memanggil `get_corrugator_item_for_receipt_row`; field `fetch_from` (Item Name/Description/Quality/Flute/Width/Length/Creasing/UOM/Basic Rate) tetap terisi otomatis lewat mekanisme `fetch_from` bawaan Frappe karena kini dipicu oleh seleksi manual yang interaktif. Handler `job_order_corrugator` mengosongkan `item_code` & `job_order_corrugator_item` saat JO No baris diganti, supaya tidak nyangkut ke JO lama.
- Endpoint whitelisted utama:
    - `get_corrugator_items_for_receipt_dialog` — data untuk dialog picker "Get Items From → Job Order Corrugator" (2 langkah, mendukung filter per-baris lewat `filtered_children`)
    - `get_corrugator_items` — variant lain untuk keperluan mapping (tanpa filter per-baris)
    - `get_corrugator_component_items` — custom search query untuk field Item Code saat diisi manual; dipanggil oleh Frappe lewat `frappe.desk.search.search_widget` (bukan dipanggil langsung), yang otomatis meng-`json.loads` param `filters` sebelum diteruskan — endpoint ini tetap jaga-jaga men-`json.loads` sendiri kalau `filters` datang sebagai string dari jalur pemanggilan lain
    - `get_corrugator_item_for_receipt_row` — mengembalikan detail baris Job Order Corrugator Item (nama baris, SO No, Due Date, Delivery Date, sisa qty pending) untuk auto-fill field non-`fetch_from` saat Item Code dipilih manual
- Unit test tersedia di `test_job_order_corrugator_receipt.py` — **kelas `TestValidateReceiptQtyVsJop1` berisi test nyata & lengkap** untuk `validate_receipt_qty_vs_corrugator` (exact/under/over qty, dengan & tanpa toleransi, agregasi multi-baris, baris tanpa link, baris dengan link yang datanya sudah hilang), dijalankan lewat `unittest` biasa (bukan `FrappeTestCase`) dengan DB helper di-stub — **tidak butuh koneksi DB Frappe live** selain `frappe.init()` untuk site_config. Kelas `TestJobOrderCorrugatorReceipt` lainnya (submit SLE/GL, cancel reversal, dst.) **masih placeholder kosong (`pass`), belum diimplementasikan**

### > Peringatan operasional

- **Jangan jalankan `bench run-tests` di site manapun yang berisi data asli** — termasuk `iib.localhost`. Ini pernah menyebabkan insiden pencemaran data (lihat `erpnext-dev-lessons.md` #58/#63/#66/#67 di workspace `~/Dev/docs/`). Untuk memverifikasi perubahan kode, jalankan test lewat `unittest` di dalam `bench execute` (lihat pola di lesson #67 — cocok dengan pola yang sudah dipakai `test_job_order_corrugator_receipt.py`), bukan `bench run-tests`.
- Setelah mengubah `job_order_corrugator_receipt.py`, **restart bench** (`bench restart`, atau restart proses `bench start`) sebelum menguji lewat browser — worker yang sedang berjalan tidak otomatis memuat ulang perubahan file Python.

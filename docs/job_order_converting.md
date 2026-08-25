## Ringkasan

**Job Order Converting** (kode dokumen: `JO{NNNN}`, sering disingkat **JO P2** / **JOP2**) adalah dokumen custom di sistem ERP (module IIB) yang memerintahkan produksi tahap **converting** (proses lanjutan dari lembaran hasil corrugator menjadi komponen jadi) untuk satu **MC Component** (Master Card Component item) tertentu, dialokasikan ke satu atau beberapa baris Sales Order.

User memilih **MC Component** (item hasil corrugator yang akan di-convert), lalu mengalokasikan qty-nya ke baris-baris Sales Order yang butuh item tersebut (manual atau lewat tombol "Get Sales Orders"). Operasi produksi (urutan proses converting) otomatis diambil dari **Master Card** kalau tersedia. Saat **Submit**, sistem otomatis membuat dan men-submit dokumen **Job Order Converting RM to WIP** (transfer stok Raw Material → WIP), mengunci qty yang sudah dialokasikan ke SO Item/Packed Item terkait (untuk kontrol toleransi over-alokasi), dan JO siap "berjalan" — hasil produksi jadinya nanti dicatat lewat dokumen **FGTS**.

Dokumen ini bersifat **submittable** (draft → submitted → cancelled), dengan status tambahan (`In Process` → `Completed`, atau `Stopped`/`Closed`) yang mengikuti progres produksi.

---

## Kapan Digunakan

Gunakan Job Order Converting setiap kali sebuah **MC Component** (item hasil produksi corrugator) sudah tersedia sebagai bahan baku dan siap diproses ke tahap converting untuk memenuhi satu atau beberapa Sales Order. Sama seperti Job Order Corrugator, dokumen ini **tetap bisa dipakai untuk SO berjenis FC** — asalkan SO tersebut belum berstatus Stopped/Closed/Cancelled.

Satu JO Converting hanya boleh berisi **satu MC Component** (`production_item`), tapi bisa mengalokasikan qty-nya ke **banyak baris Sales Order sekaligus** (termasuk campuran SO customer yang berbeda, atau baris bundle "Set" dan baris item langsung sekaligus).

---

## Alur Kerja

### 1. Isi Header

| Field | Keterangan |
| --- | --- |
| **Company** | Default: PT. Interpak Industries Batam (tersembunyi di form) |
| **MC Component** (`production_item`) | Wajib. Item hasil corrugator yang akan di-convert. Daftar pilihan otomatis difilter ke item Master Card milik **Customer** yang dipilih (kalau Customer diisi); kalau Customer kosong, fallback ke semua item bergroup Component |
| **On Hand Qty** | Read-only, ditarik otomatis dari stok gudang `Stores - IIB` untuk MC Component yang dipilih (bukan RM/WIP — murni referensi qty jadi yang sudah ada di Stores) |
| **Customer** | Opsional — kalau diisi, mempersempit pilihan MC Component **dan** hasil tombol "Get Sales Orders" ke SO milik customer tersebut. Mengganti Customer otomatis mengosongkan MC Component (supaya user memilih ulang dari daftar yang terfilter) |
| **Posting Date** | Default hari ini |
| **Due Date** | Wajib diisi |
| **Qty to Convert** | Jumlah total yang mau dikonversi di JO ini. Dipakai sebagai qty transfer RM→WIP saat submit — **harus > 0** |
| **Remark** | Catatan bebas (opsional) — auto-terisi dari field `remark` Master Card saat baris SO pertama ditambahkan lewat picker (bisa diedit ulang manual) |

**Quantity Tracking** (section collapsible, semua read-only, dihitung ulang tiap kali dokumen divalidasi — lihat [Rollup Qty](#rollup-qty-quantity-tracking)): Total SO Qty, Delivered, Closed, JO Qty (In Process), Qty RM.

### 2. Alokasi ke Sales Order — Tabel "Job Order Converting Items"

Field `sales_order_items` **tidak wajib diisi** (`reqd` di-nonaktifkan lewat client script) — JO Converting boleh disubmit tanpa alokasi SO sama sekali (murni transfer RM→WIP tanpa keterlacakan ke SO tertentu), meskipun umumnya diisi. Baris kosong (semua field blank) otomatis dibuang sendiri baik di client maupun di server (`before_validate`), jadi tidak perlu khawatir baris placeholder kosong tertinggal.

Ada 2 cara mengisi baris:

**A. Manual** — tambah baris, isi **SO No** (Sales Order) dan **Qty**; `sales_order_item` (referensi baris SO Item/Packed Item spesifik) tidak tersedia sebagai field yang bisa diisi lewat UI grid biasa (field-nya tersembunyi) — jalur manual murni ini pada praktiknya jarang dipakai; jalur B di bawah adalah cara utama.

**B. Tombol "Get Sales Orders"** (di header, sebelah field MC Component) — hanya berfungsi kalau **MC Component** sudah diisi. Sistem mencari **semua** Sales Order (submitted, belum Stopped/Closed/Cancelled — dan kalau Customer diisi, dibatasi ke customer tersebut) yang punya baris MC Component ini — baik sebagai Packed Item (baris bundle/"Set") maupun Sales Order Item langsung — lalu **mengganti seluruh isi tabel** dengan satu baris per SO Item yang masih punya qty terbuka (`qty − delivered_qty − qty yang sudah dialokasikan ke JO Converting submitted lain`). Kalau MC Component belum diisi otomatis dari baris SO sebelumnya, sistem juga otomatis mengisi MC Component dari item baris pertama yang ditemukan.

> Bundle SO (baris Product Bundle/"Set") diprioritaskan: kalau SO punya baris Packed Item yang cocok, baris itu yang dipakai (bukan baris Sales Order Item parent-nya) — supaya alokasi selalu ke level komponen aktual, bukan ke qty Set.

| Field | Keterangan |
| --- | --- |
| **SO No** | Wajib per baris. Kolom tampil di list view child table |
| **SO Date**, **PO No**, **PO Date**, **UOM** | Read-only, ditarik dari Sales Order/SO Item terkait saat baris diproses lewat `validate()` |
| **Qty** | Jumlah yang dialokasikan dari baris SO ini ke JO Converting. Harus > 0, dan **tidak boleh melebihi qty yang masih tersedia** di baris SO tersebut (lihat [Qty Tersedia per Baris SO](#qty-tersedia-per-baris-sales-order)) |
| **Remark** | Catatan per baris — default terisi dari `remark` Master Card MC Component (lihat header) |
| **Sales Order Item**, **Item Code**, **Delivery Date**, **Customer**, **SO Status** | Tersembunyi di form (field internal) — otomatis diisi/divalidasi sistem, dipakai untuk kontrol konsistensi & qty |

Semua baris di tabel ini **harus** mengacu ke item yang **sama persis** dengan MC Component header — kalau ada baris yang item-nya berbeda (misal sisa dari MC Component sebelumnya sebelum diganti), submit/save akan **ditolak**.

### 3. Operations (opsional)

Section "Operations" berisi urutan proses converting (mesin/tahapan). Kalau **Master Card** milik MC Component punya baris **Processes** untuk komponen yang bersangkutan, baris-baris ini **otomatis diisi** saat MC Component dipilih pertama kali (dan tabel Operations masih kosong) — meniru urutan `sequence`, `section` (Section Group), estimasi waktu, dan deskripsi dari Master Card.

| Field | Keterangan |
| --- | --- |
| **Seq** | Urutan proses |
| **Section Group** | Wajib. Hanya section bertipe **group** & tidak disabled yang bisa dipilih |
| **Production Section** | Wajib **sebelum submit** (boleh kosong saat masih draft — lihat [Validasi](#validasi)). Difilter dinamis: hanya section **leaf** (bukan group) yang merupakan **anak** dari Section Group baris yang sama. Mengganti Section Group mengosongkan kembali Production Section baris itu |
| **Est Time (mins)**, **Description** | Opsional, informasi tambahan |
| **Completed Qty**, **Status** (Pending/In Progress/Completed) | Read-only — diisi oleh proses produksi di luar dokumen ini (Production Process Item), lalu di-*roll up* kembali ke sini lewat tombol **Refresh Qty** (lihat di bawah) |

> Mengganti **MC Component** pada dokumen yang sudah pernah tersimpan (bukan dokumen baru) akan **mengosongkan seluruh tabel Operations** — karena operasi lama sudah tidak relevan untuk komponen yang baru.

### 4. Submit

Saat tombol **Submit** ditekan:

1. Sistem memvalidasi minimal ada 1 baris di **Job Order Converting Items** (berbeda dari saat draft, di mana tabel ini boleh kosong)
2. Setiap baris **Operations** yang ada harus sudah punya **Production Section** terisi
3. Validasi toleransi over-alokasi dijalankan (lihat [Validasi Toleransi](#validasi-toleransi-saat-submit))
4. Sistem menghitung ulang & mengunci qty alokasi (`custom_wip_quantity`) ke SO Item/Packed Item terkait
5. Dokumen **Job Order Converting RM to WIP** dibuat otomatis (draft) lalu **langsung disubmit oleh sistem** — memindahkan `Qty to Convert` dari Raw Material Warehouse ke WIP Warehouse (lihat [RM to WIP](#rm-to-wip-transfer-raw-material--wip))
6. Status header di-set ke **"In Process"**

---

## Qty Tersedia per Baris Sales Order

Fungsi `get_so_item_available_qty` menghitung qty yang masih bisa dialokasikan dari sebuah baris SO Item/Packed Item:

```
available_qty = qty_baris_SO − delivered_qty − qty_WIP_yang_sudah_dialokasikan
```

- **qty_baris_SO** & **delivered_qty**: langsung dari Sales Order Item, atau (untuk baris bundle) dari Packed Item + rasio delivered_qty terhadap qty milik SO Item parent-nya.
- **qty_WIP_yang_sudah_dialokasikan**: dibaca dari field `custom_wip_quantity` (kalau kolom ini ada di database — lihat [Catatan Teknis](#catatan-teknis-untuk-tim-itdeveloper)) pada Packed Item/Sales Order Item terkait, yang berisi **total qty dari semua Job Order Converting *submitted*** yang mengacu ke baris SO tersebut. Field ini disinkronkan ulang otomatis setiap kali sebuah JO Converting **submit, cancel, atau dihapus** (lihat [Sinkronisasi Qty](#sinkronisasi-qty-custom_wip_quantity)). Saat mengedit JO Converting yang sudah ada, qty milik dokumen ini sendiri dikecualikan dari perhitungan supaya user bisa menyesuaikan qty baris tanpa dianggap "bentrok dengan dirinya sendiri".

Baris SO dengan `available_qty` = 0 tidak akan muncul saat tombol **"Get Sales Orders"** dipakai.

---

## Sinkronisasi Qty (`custom_wip_quantity`)

Setiap kali JO Converting **submit**, **cancel**, atau **dihapus** (`on_trash`), sistem menghitung ulang total qty JO Converting **submitted** untuk tiap baris SO Item/Packed Item yang tersentuh (baris di dokumen ini sekarang **maupun** baris yang sempat ada di versi sebelumnya sebelum disimpan ulang), lalu menyimpannya ke field `custom_wip_quantity` pada Packed Item atau Sales Order Item yang bersangkutan. Field ini dipakai lagi sebagai baseline saat menghitung qty tersedia (di atas) maupun validasi toleransi (di bawah).

---

## Validasi Toleransi (saat Submit)

Sebelum submit berhasil, sistem mengecek agar **total qty JO Converting (dokumen ini + semua JO Converting submitted lain untuk baris SO yang sama) tidak melebihi qty SO + toleransi**, dikonfigurasi di singleton **IIB Settings**, tabel child **IIB Settings Converting Tolerance** (`converting_qty` = ambang qty maksimum tier, `converting_toleransi` = toleransi lebih untuk tier tersebut — logika tier pencarian identik dengan Job Order Corrugator, lihat `job_order_corrugator.md`).

Perhitungan ini **persis meniru** validasi toleransi Job Order Corrugator, tapi di level SO Item/Packed Item (bukan per-item produksi): `qty SO baris tersebut` dibandingkan terhadap `custom_wip_quantity` (qty JO Converting submitted lain, tidak termasuk dokumen ini) + qty dokumen ini.

Kalau tidak ada tabel toleransi dikonfigurasi sama sekali → validasi dilewati. Kalau melebihi batas → submit **ditolak** dengan pesan error yang menyebutkan SO Item, item, qty, toleransi, dan batas maksimum.

---

## Rollup Qty (Quantity Tracking)

Field-field di section "Quantity Tracking" dihitung ulang setiap kali dokumen divalidasi (`validate()`), murni untuk tampilan/monitoring:

| Field | Cara Hitung |
| --- | --- |
| **Total SO Qty** | Jumlah `qty` seluruh baris Job Order Converting Items |
| **Delivered** | Untuk tiap baris SO, `min(qty baris JO, delivered_qty baris SO tersebut)` — dijumlahkan |
| **Closed** | Jumlah `qty` baris JO yang Sales Order induknya sudah berstatus **Closed** |
| **JO Qty (In Process)** | `max(Qty to Convert − Converted Qty, 0)` — sisa yang masih "mengambang" di WIP, belum jadi hasil converting |
| **Qty RM** | Stok on-hand MC Component saat ini di warehouse Raw Material default (dari **IIB Settings**) |

---

## RM to WIP (Transfer Raw Material → WIP)

**Job Order Converting RM to WIP** adalah dokumen turunan yang dibuat **otomatis** (dan langsung disubmit) saat JO Converting disubmit — mencatat pemindahan stok `Qty to Convert` dari **Raw Material Warehouse** (default IIB Settings) ke **WIP Warehouse** milik JO ini. Sama seperti Job Order Corrugator Receipt, class-nya meng-*extend* `StockController` bawaan ERPNext sehingga membuat **Stock Ledger Entry** berpasangan (keluar dari RM, masuk ke WIP) dan **GL Entry** seimbang (Debit akun WIP, Kredit akun RM — kecuali kedua warehouse berbagi akun GL yang sama, dalam hal itu tidak ada jurnal yang dibuat karena tidak ada dampak GL bersih).

Tombol **View → Stock Ledger** (muncul di form JO Converting saat submitted dan `transfer_rm_doc` sudah terisi) langsung membuka laporan Stock Ledger terfilter ke dokumen RM to WIP tersebut.

> Dokumen RM to WIP **tidak dibuat/disubmit manual oleh user** — sepenuhnya otomatis mengikuti siklus hidup JO Converting.

---

## Operations, Refresh Qty, dan Status Header

Kalau tabel Operations diisi, tombol **Refresh Qty** (muncul saat submitted & ada baris Operations) memanggil endpoint yang **meng-agregasi ulang** `completed_qty` tiap baris Operation dari seluruh **Production Process Item** yang belum dibatalkan (dokumen tracking proses produksi aktual — di luar cakupan dokumen ini), lalu status header **JO Converting** ikut disesuaikan otomatis (`_refresh_header_status`):

- Semua Operation **Completed** → header jadi **"Completed"**
- Ada minimal satu Operation **In Progress** atau **Completed** → header **"In Process"**
- Selain itu (semua masih Pending) → tetap **"In Process"**

> Kalau tabel Operations **kosong**, status header **tidak** dikendalikan oleh mekanisme ini — murni mengikuti `produced_qty` (lihat bagian FGTS di bawah) dan status terminal manual (Stopped/Closed/Cancelled tidak pernah ditimpa otomatis oleh proses manapun).

---

## FGTS & Produced Qty

**FGTS** (Finished Goods Tracking System) adalah dokumen terpisah yang mencatat **hasil jadi** produksi converting (analog dengan Job Order Corrugator Receipt, tapi dengan alur QC 2-tahap: submit → **"Waiting QC"** [dokumen terkunci, belum ada pergerakan stok] → Approve QC → **"OK QC"** [barulah stok berpindah langsung dari WIP/Raw Material ke Stores]).

Setiap kali sebuah FGTS **disubmit atau dibatalkan**, sistem otomatis mencari JO Converting yang relevan (`job_order_converting` di-resolve otomatis dari `production_item` baris FGTS, atau fallback ke Sales Order-nya) dan memanggil `update_produced_qty()`:

- **Converted Qty** (`produced_qty`) dihitung ulang dari total `total_qty` seluruh **FGTS submitted** yang menunjuk ke JO ini
- **JO Qty (In Process)** dihitung ulang: `max(Qty to Convert − Converted Qty, 0)`
- Status header disesuaikan ulang (bisa berubah ke **Completed** kalau `produced_qty ≥ qty`), kecuali status sudah terminal (Stopped/Closed/Cancelled)

> Detail lengkap FGTS (validasi, alur QC, perhitungan valuasi transfer) berada di luar cakupan dokumen ini — lihat kode `iib/iib/doctype/fgts/fgts.py` untuk referensi teknis.

---

## Return Components (WIP → Raw Material)

Tombol **Create → Return Components** (muncul saat status **Completed**/**Closed** dan masih ada sisa `JO Qty (In Process)` > 0) membuat **draft Stock Entry** standar ERPNext (tipe sesuai **IIB Settings** → `converting_start_stock_entry_type`, default "Material Transfer") untuk mengembalikan sisa material yang belum terpakai dari WIP Warehouse kembali ke Raw Material Warehouse. Qty yang diisi otomatis = seluruh sisa `JO Qty (In Process)`.

> Stock Entry hasil tombol ini **harus disubmit manual oleh user** (tidak auto-submit), dan **tidak ada sinkronisasi balik otomatis** ke field `jo_qty_in_process` JO Converting setelah Stock Entry tersebut disubmit — field itu tetap murni dihitung dari `qty − produced_qty` (lihat [Rollup Qty](#rollup-qty-quantity-tracking)). Jadi tombol ini adalah aksi koreksi stok fisik, bukan bagian dari alur kalkulasi qty JO Converting.

---

## Status Manual: Stop / Re-open / Close

| Tombol | Kondisi Muncul | Efek |
| --- | --- | --- |
| **Status → Stop** | Submitted, status bukan Completed/Cancelled/Closed | Set status ke **"Stopped"** — produksi dihentikan sementara |
| **Status → Re-open** | Status **"Stopped"** | Kembali ke **"In Process"** |
| **Status → Close** | Submitted, status bukan Completed/Cancelled/Closed (ada konfirmasi dialog) | Set status ke **"Closed"** — final, "tidak ada perubahan lagi diizinkan" |

Ketiga aksi dijalankan lewat endpoint yang sama (`stop_job_order`), dibatasi permission **submit**, dan hanya berlaku untuk dokumen **submitted**.

---

## Pembatalan (Cancel)

Sebelum cancel diproses, sistem memeriksa apakah ada **Job Order Converting RM to WIP yang submitted** menunjuk ke dokumen ini — kalau ada, cancel **ditolak** (RM to WIP harus dicancel dulu; catatan: cancel RM to WIP sendiri **tidak diblokir balik** oleh dokumen ini — urutan yang berlaku: cancel RM to WIP dulu, baru JO Converting bisa dicancel).

Kalau lolos pengecekan, saat cancel:

1. Kalau `transfer_rm_doc` masih berstatus **draft** (kasus jarang), dihapus otomatis
2. Status header di-set ke **"Cancelled"**
3. `custom_wip_quantity` pada SO Item/Packed Item terkait dihitung ulang, dengan dokumen ini **dikecualikan** dari perhitungan (qty dari dokumen yang dibatalkan otomatis lepas, membebaskan slot alokasi untuk JO Converting lain)

---

## Penomoran Dokumen

Nomor Job Order Converting dibuat otomatis dengan format **`JO{NNNN}`**, contoh: `JO0001`.

- `NNNN` = nomor urut 4 digit
- **Berbeda dari Job Order Corrugator** — nomor ini **tidak pernah reset per tahun** (counter dipanggil dengan `period=None`), jadi nomor urut terus naik lintas tahun
- Diatur lewat singleton **IIB Document Naming Settings** (counter key: `jop2`)

Dokumen **Job Order Converting RM to WIP** memakai naming series standar Frappe `JRMWIP-.YY.-.#####` (reset per tahun, terpisah dari sistem penomoran IIB custom).

---

## Error Umum & Penyebabnya

| Pesan Error | Penyebab | Solusi |
| --- | --- | --- |
| "Sales Order Item rows reference different items than MC Component ...: ..." | Ada baris di tabel Job Order Converting Items yang item-nya beda dari MC Component header | Hapus baris tersebut, atau ganti MC Component agar sesuai |
| "Sales Order Item is required in row ..." | Baris tanpa `sales_order_item` terisi (biasanya hanya terjadi kalau isi manual tidak lewat picker) | Isi ulang lewat tombol "Get Sales Orders" |
| "Sales Order Item row ...: Qty must be positive" | Qty baris diisi 0 atau negatif | Isi qty > 0 |
| "Sales Order Item ... does not exist" | Referensi baris SO Item/Packed Item sudah rusak/terhapus | Hapus baris, ambil ulang lewat "Get Sales Orders" |
| "Sales Order ... is not open for Job Order Converting allocation" | SO sumber baris berstatus Stopped/Closed/Cancelled, atau belum submitted | Pilih SO lain yang masih aktif |
| "Row ...: Sales Order does not match Sales Order Item ..." | Field SO No baris tidak konsisten dengan `sales_order_item` internalnya | Hapus & tambah ulang baris lewat picker |
| "Row ...: Sales Order Item ... is for item ..., not ..." | Baris SO ternyata bukan untuk MC Component header | Perbaiki MC Component atau hapus baris tsb |
| "Sales Order Item ...: requested qty ... exceeds remaining available qty ..." | Total qty yang diminta di seluruh baris untuk SO Item yang sama melebihi qty tersedia (lihat [Qty Tersedia](#qty-tersedia-per-baris-sales-order)) | Kurangi qty baris, atau pisah ke JO Converting lain setelah SO Item tersebut punya sisa qty lagi |
| "At least one Sales Order Item is required before submitting Job Order Converting" | Submit tanpa baris alokasi SO sama sekali | Tambahkan minimal 1 baris (draft boleh kosong, submit tidak) |
| "Operation row ...: Production Section is required before submitting Job Order Converting" | Ada baris Operations yang Production Section-nya masih kosong saat submit | Lengkapi Production Section tiap baris Operations |
| "Operation row ...: Section Group is required" / "does not exist" / "must be an enabled group section" | Section Group baris Operations kosong, tidak valid, atau bukan section aktif bertipe group | Perbaiki pilihan Section Group |
| "Operation row ...: Production Section ... does not exist" / "must be an enabled detail section" / "must be under Section Group ..." | Production Section tidak valid, bukan section leaf aktif, atau bukan turunan dari Section Group baris tsb | Pilih Production Section yang sesuai — daftar sudah difilter otomatis berdasarkan Section Group baris |
| "SO Item ... (item ...): total JO P2 qty ... exceeds SO qty ... + tolerance ... = ..." | Total qty JO Converting (dokumen ini + submitted lain) melebihi qty SO + toleransi | Kurangi qty baris ini, atau selesaikan/tambah kapasitas SO dulu |
| "Set Raw Material Warehouse in IIB Settings before submitting Job Order Converting" | Warehouse Raw Material default belum dikonfigurasi | Isi field **Raw Material Warehouse** di IIB Settings |
| "WIP Warehouse not set" | Field WIP Warehouse dokumen kosong (harusnya otomatis dari IIB Settings) | Isi field **WIP Warehouse** di IIB Settings, atau isi manual di dokumen |
| "Qty to Convert must be greater than 0" | Header Qty to Convert diisi 0 | Isi qty > 0 |
| "Cannot cancel: submitted Job Order Converting RM to WIP ... exists. Cancel it first." | Mencoba cancel JO Converting yang RM to WIP-nya sudah submitted | Cancel dulu dokumen RM to WIP terkait |
| "Job Order Converting must be submitted before starting" / "Cannot start a {status} Job Order Converting" | Memanggil aksi start pada dokumen draft atau berstatus terminal | Submit dokumen dulu, atau cek statusnya |
| "Job Order Converting must be submitted before Return Components" / "No quantity in WIP to return" | Tombol Return Components dipakai pada dokumen draft, atau sudah tidak ada sisa qty in-process | Submit dulu, atau tidak perlu return kalau sisa sudah 0 |

---

## Dokumen Terkait (Doctype)

- **Job Order Converting Sales Order Item** — child table alokasi qty ke baris Sales Order/Packed Item
- **Job Order Converting Operation** — child table urutan proses produksi, diseed dari Master Card Processes
- **Job Order Converting RM to WIP** — dokumen transfer stok RM→WIP, dibuat & disubmit otomatis saat JO Converting submit
- **Job Order Converting RM to WIP Item** — child table item pada RM to WIP
- **FGTS** / **FGTS Item** — dokumen hasil produksi converting (finished goods, dengan alur QC), mengupdate `produced_qty` balik ke JO Converting
- **IIB Production Section** — struktur Section Group (kategori) & Production Section (leaf) yang dipakai tabel Operations
- **IIB Settings** — singleton konfigurasi: Raw Material Warehouse, WIP Warehouse, Stock Entry Type untuk Return Components, serta tabel toleransi (`IIB Settings Converting Tolerance`)
- **Master Card** / **Master Card Item** / **Master Card Process** — sumber MC Component, urutan operasi, dan remark default
- **Sales Order** / **Sales Order Item** / **Packed Item** — sumber baris alokasi; field `custom_wip_quantity` di-sync balik oleh JO Converting
- **Job Order Corrugator** — proses produksi tahap sebelumnya; lihat `job_order_corrugator.md`

---

## Catatan Teknis (untuk tim IT/Developer)

- Lokasi kode: `iib/iib/doctype/job_order_converting/job_order_converting.py`, client script: `job_order_converting.js`
- Nomor dokumen dibuat lewat `iib.iib.utils.naming.get_next_iib_number` (counter key `jop2`, 4 digit, `period=None` → **tidak pernah reset per tahun**, beda dari Corrugator/SO Batch)
- Toleransi dibaca lewat helper bersama `iib.iib.utils.tolerance.lookup_tolerance` (sama seperti Job Order Corrugator, tabel tolerance terpisah: `IIB Settings Converting Tolerance`)
- Modul secara sengaja mendukung **dua sumber baris SO** (`SO_LINE_DOCTYPES = ("Packed Item", "Sales Order Item")`) — helper `get_so_line_doctype`/`get_so_line_details` menormalkan keduanya jadi satu shape data, karena SO bundle ("Set") menyimpan alokasi component di Packed Item, sedangkan SO non-bundle langsung di Sales Order Item
- Field `custom_wip_quantity` **kondisional** — helper `has_wip_field()` mengecek dulu apakah kolom ini benar-benar ada di tabel (`frappe.db.has_column`) sebelum membacanya. Kalau kolom belum ter-install (migrasi custom field belum jalan di site tertentu), sistem **fallback ke query live** (`get_live_so_item_wip_qty` — SUM langsung dari `Job Order Converting Sales Order Item` submitted) alih-alih gagal — jadi behavior tetap benar meski field cache-nya belum ada, hanya lebih lambat
- Endpoint whitelisted utama:
    - `fetch_all_so_items_for_converting` — logic di balik tombol "Get Sales Orders" (replace seluruh tabel)
    - `get_items_from_so_for_converting` — mapper per-SO (dipakai juga oleh alur "Sales Order → Create → Job Order Converting" dari sisi Sales Order, di luar cakupan dokumen ini)
    - `get_so_query_for_production_item` / `get_component_items_for_customer` — custom search query untuk field Link (Sales Order by production_item, MC Component by customer)
    - `get_operations_for_item` — ambil Master Card Processes untuk auto-seed tabel Operations
    - `get_item_on_hand_qty` — qty on-hand di `Stores - IIB` untuk field "On Hand Qty"
    - `start_job_order` — aksi "Start" idempotent (submit/rebuild RM to WIP) — **tidak dipanggil dari tombol manapun di `job_order_converting.js` saat ini**; kemungkinan dipakai dari halaman/list lain atau disiapkan untuk pemakaian mendatang
    - `refresh_operations_qty` — agregasi ulang `completed_qty` Operations dari Production Process Item, lalu refresh status header
    - `stop_job_order` — Stop/Re-open/Close manual
    - `make_return_components` — bangun draft Stock Entry untuk tombol Return Components
- Status **tidak** memiliki mekanisme tunggal terpusat: dipengaruhi oleh (a) `on_submit`/`on_cancel` langsung, (b) `_refresh_header_status()` dari Operations (hanya kalau tabel Operations tidak kosong), dan (c) `update_produced_qty()` yang dipanggil dari FGTS. Method `get_status()`/`update_status()` tersedia sebagai penghitung status "murni dari data" tapi **tidak dipanggil otomatis di lifecycle utama** (`validate`/`on_submit`) — hanya dipanggil eksplisit dari RM to WIP (`_update_jo_status`) dan `refresh_operations_qty`
- Unit test (`test_job_order_converting.py`) **kosong total** (`class TestJobOrderConverting(FrappeTestCase): pass`) — tidak ada satu pun test case, berbeda dari Job Order Corrugator yang setidaknya punya stub `skipTest`. Jangan mengandalkan coverage otomatis apa pun untuk doctype ini
- Rename historis: dulunya disebut "P2"/"JOP2" sebelum di-rename ke "Converting" via patch `iib.patches.v0_0.rename_p1_p2_to_corrugator_converting` — sisa singkatan lama (`jop2` counter key, `JO P2` di beberapa pesan error) masih ada, normal dan bukan bug (pola sama seperti Job Order Corrugator)

### Peringatan operasional

- **Jangan jalankan `bench run-tests` di site manapun yang berisi data asli** — termasuk `iib.localhost`. Ini pernah menyebabkan insiden pencemaran data (lihat `erpnext-dev-lessons.md` #58/#63/#66/#67 di workspace `~/Dev/docs/`). Untuk memverifikasi perubahan kode, jalankan test lewat `unittest` di dalam `bench execute` (lihat pola di lesson #67), bukan `bench run-tests`.
- Setelah mengubah `job_order_converting.py`, **restart bench** (`bench restart`, atau restart proses `bench start`) sebelum menguji lewat browser — worker yang sedang berjalan tidak otomatis memuat ulang perubahan file Python.

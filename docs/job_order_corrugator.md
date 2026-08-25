## > Ringkasan

**Job Order Corrugator** (kode dokumen: `IIB{YY}{NNNN}`, sering disingkat **JO P1** / **JOP1**) adalah dokumen custom di sistem ERP (module IIB) yang digunakan untuk memerintahkan produksi tahap **corrugator** (pembuatan lembaran karton bergelombang) berdasarkan Sales Order yang sudah **submitted**.

User memilih Sales Order (atau beberapa sekaligus lewat dialog picker), sistem menarik item-nya (termasuk mem-*expand* Product Bundle/"Set" menjadi komponen-komponen aslinya), lalu menambahkan spesifikasi papan (board spec), setting mesin, dan tanggal produksi. Saat **Submit**, sistem mengunci qty yang sudah dijalankan ke SO Item terkait (untuk kontrol toleransi over-produksi) dan dokumen siap menerima **Job Order Corrugator Receipt** (hasil produksi aktual).

Dokumen ini bersifat **submittable** (draft → submitted → cancelled), dengan status tambahan (`To Receive` → `Partially Received` → `Completed`, atau `Closed`) yang mengikuti progres penerimaan hasil produksi.

---

## > Kapan Digunakan

Gunakan Job Order Corrugator setiap kali Sales Order (General **maupun** FC) sudah siap masuk produksi tahap corrugator. Job Order Corrugator **tetap diizinkan untuk SO berjenis FC** — ini justru tujuan utamanya: produksi bisa mulai lebih awal sebelum PO resmi customer turun (lihat `so_batch.md` bagian "Blokir Delivery Note & Sales Invoice untuk SO yang Masih FC").

Satu JO Corrugator boleh berisi baris dari **beberapa Sales Order sekaligus** (misalnya menggabungkan beberapa SO customer yang sama untuk 1 kali jalan produksi).

---

## > Alur Kerja

### > 1. Isi Header

| Field | Keterangan |
| --- | --- |
| **Company** | Default: PT. Interpak Industries Batam (tersembunyi di form) |
| **Customer** | Read-only — otomatis terisi kalau **semua baris item** berasal dari 1 customer yang sama; dikosongkan kalau baris item berasal dari lebih dari 1 customer |
| **Transaction Date** | Default hari ini |
| **Due Date** | Wajib diisi. Tidak boleh lebih awal dari Transaction Date. Mengisi default `due_date` tiap baris item baru, dan field ini juga membatasi tanggal minimum yang bisa dipilih di datepicker-nya sendiri |
| **% Received** | Read-only, terhitung otomatis dari qty yang sudah diterima lewat Receipt |
| **Remarks** | Catatan bebas (opsional) |

### > 2. Isi Tabel "Items"

Ada 2 cara mengisi baris item:

**A. Manual** — isi Sales Order, lalu Item Code (hanya item bergroup **Component** dan berstatus stock item yang bisa dipilih; daftar Item Code otomatis difilter agar hanya menampilkan item milik SO yang dipilih di baris itu — termasuk komponen hasil *expand* Product Bundle). Setelah Item Code dipilih, `sales_order_item` (baris SO Item terkait) otomatis dicari & diisi, dan seluruh spesifikasi papan (lihat tabel field di bawah) otomatis ditarik dari Item Master.

**B. Tombol "Get Items From → Sales Order"** (hanya muncul saat dokumen masih draft) — membuka dialog picker dengan filter Customer / Sales Order / Tanggal / Item Code serta checkbox **"Open qty only"** (default aktif, hanya menampilkan baris SO yang qty JO Corrugator-nya belum penuh). User bisa centang baris satu per satu (Product Bundle otomatis ditampilkan per komponen), lalu klik "Get Items" untuk menambahkan semua baris tercentang sekaligus ke tabel Items.

| Field | Keterangan |
| --- | --- |
| **Sales Order** | Wajib. Hanya SO yang **submitted** dan belum Closed/Cancelled/Completed yang bisa dipilih |
| **Sales Order Item** | Baris SO Item terkait — otomatis diisi sistem, tidak perlu diisi manual |
| **Item Code** | Item **Component** (bukan Set/bundle) — untuk baris SO yang item-nya Product Bundle, di sinilah komponen hasil *expand*-nya dipilih |
| **Qty Req** | Jumlah yang mau diproduksi di JO ini. Harus > 0 |
| **Due Date** | Batas waktu produksi baris ini. Tidak boleh sebelum Transaction Date header |
| **Delivery Date**, **SO Date**, **Customer**, **Rate** | Read-only, ditarik otomatis dari Sales Order / SO Item terkait |
| **Received Qty**, **Pending Qty** | Read-only — terisi/ter-update otomatis dari Job Order Corrugator Receipt yang sudah submitted (lihat [Penerimaan](#penerimaan-job-order-corrugator-receipt)) |

**Board Spec** (section muncul begitu Item Code diisi, semua read-only — ditarik dari Item Master): Quality, Flute, Width, Length, D/C, Single/Double, Set/Pcs, Part No.

**Crease & Joints** (section muncul begitu Item Code diisi, semua read-only — ditarik dari Item Master): Crease W, Crease L, Slotting, Display, Joint 1, Joint 2.

**Machine Settings** (diisi manual oleh user): Running Width, Running Length, Setting, Cutting Number.

**Production** (read-only, dihitung otomatis di client-side untuk tampilan/print saja — lihat [Perhitungan Produksi](#perhitungan-produksi-tampilan-saja)): Up Width, Up Length, UpW×UpL, Qty (qty_production).

### > 3. Submit

Saat tombol **Submit** ditekan, sistem memvalidasi toleransi over-produksi (lihat [Validasi Toleransi](#validasi-toleransi-saat-submit)), lalu status berubah menjadi **"To Receive"** dan qty JO Corrugator dikunci ke SO Item/Packed Item terkait (`custom_corrugator_qty`) untuk kontrol toleransi di JO Corrugator berikutnya maupun saat Job Order Corrugator Receipt dibuat.

---

## > Perhitungan Produksi (tampilan saja)

Field-field di section "Production" **tidak divalidasi di server** — murni kalkulasi client-side (`job_order_corrugator.js`) untuk membantu operator melihat estimasi, dan ikut tercetak di form/print:

- **Up Width** = `floor(Running Width / Width)`
- **Up Length** = `floor(Running Length / Length)`
- **UpW × UpL** = `Up Width × Up Length`
- **Qty (Production)** = `((Qty Req + Setting) / D/C) / (UpW × UpL) × Set/Pcs`

Field-field ini otomatis dihitung ulang tiap kali Width, Length, D/C, Set/Pcs, Qty Req, Running Width, Running Length, atau Setting berubah.

---

## > Validasi Toleransi (saat Submit)

Sebelum submit berhasil, sistem mengecek agar **total qty JO Corrugator (across semua JO Corrugator submitted) tidak melebihi qty SO Item + toleransi** yang dikonfigurasi di singleton **IIB Settings**, tabel child **IIB Settings Corrugator Tolerance** (`corrugator_qty` = ambang qty maksimum tier, `corrugator_toleransi` = toleransi lebih untuk tier tersebut; tier dicari secara **tier pertama yang qty maksimumnya ≥ qty SO** — kalau qty SO melebihi semua tier, dipakai tier tertinggi).

- **Item non-bundle**: `qty SO Item` dibandingkan langsung terhadap total qty JO Corrugator (dokumen ini + semua JO Corrugator submitted lain untuk SO Item yang sama, tidak termasuk dokumen ini sendiri saat amend).
- **Item hasil expand Product Bundle**: qty referensi = `qty Set pada SO Item × qty komponen per Set` (dari tabel Product Bundle Item), dibandingkan terhadap total qty JO Corrugator untuk kombinasi (SO Item, Item komponen) yang sama.

Kalau tidak ada tabel toleransi dikonfigurasi sama sekali → validasi ini dilewati (boleh qty berapa saja).

Kalau total qty melebihi batas → submit **ditolak** dengan pesan error yang menyebutkan qty SO, toleransi, dan batas maksimum yang diizinkan.

---

## > Sinkronisasi Qty ke Sales Order (`custom_corrugator_qty`)

Setelah submit **maupun** cancel, sistem menghitung ulang total qty JO Corrugator yang **submitted** untuk tiap SO Item yang tersentuh, lalu menyimpannya ke:

- **Item non-bundle** → field `custom_corrugator_qty` pada **Sales Order Item**
- **Item hasil expand Product Bundle** → field `custom_corrugator_qty` pada **Packed Item** (per komponen, bukan di level parent bundle — karena qty bundle di level SO Item tidak relevan untuk tracking corrugator)

Field ini dipakai lagi sebagai baseline saat validasi toleransi JO Corrugator berikutnya, dan ditampilkan di dialog "Get Items From → Sales Order" (kolom "Cor Qty") supaya user tahu berapa qty yang sudah pernah di-order sebelum menambah baris baru.

---

## > Penerimaan (Job Order Corrugator Receipt)

Tombol **Create → Job Order Corrugator Receipt** (muncul saat dokumen submitted dan statusnya belum Completed/Closed/Cancelled) membuat draft **Job Order Corrugator Receipt** baru berisi seluruh baris yang qty-nya masih pending (`qty − received_qty > 0`), lengkap dengan Target Warehouse (`Raw Material - IIB`) dan default akun GL dari **IIB Settings**.

Setiap kali sebuah Receipt **disubmit atau dibatalkan**, sistem menghitung ulang `received_qty` & `pending_qty` tiap baris JO Corrugator dari total Receipt yang **submitted**, lalu memperbarui status header otomatis:

| Kondisi | Status |
| --- | --- |
| Belum ada qty diterima | To Receive |
| Sebagian qty diterima | Partially Received |
| Seluruh qty diterima | Completed |

> Status **Closed** dan **Cancelled** tidak pernah ditimpa otomatis oleh proses ini.

Detail lengkap proses stock/GL Receipt ada di dokumen terpisah [`job_order_corrugator_receipt.md`](job_order_corrugator_receipt.md).

---

## > Status Manual: Close / Re-open

Tombol **Status → Close** (muncul saat status "To Receive"/"Partially Received") menutup JO Corrugator secara manual meskipun belum diterima penuh — misalnya kalau sisa qty diputuskan tidak akan diproduksi lagi.

Tombol **Status → Re-open** (muncul saat status "Closed") membuka kembali dan langsung menghitung ulang status dari data received_qty terkini (bisa jadi kembali ke "To Receive", "Partially Received", atau "Completed" tergantung data aktual).

Kedua aksi ini hanya bisa dijalankan oleh user dengan hak **submit** pada Job Order Corrugator, dan hanya berlaku untuk dokumen yang **submitted** (`docstatus = 1`).

---

## > Pembatalan (Cancel)

Sebelum cancel diproses, sistem memeriksa apakah ada **Job Order Corrugator Receipt yang submitted** yang menunjuk ke dokumen ini — kalau ada, cancel **ditolak** (harus cancel Receipt-nya dulu).

Kalau lolos pengecekan, saat cancel:

1. Semua **Job Order Corrugator Receipt berstatus draft** yang menunjuk ke dokumen ini **langsung dihapus otomatis** (bukan sekadar dibiarkan, karena draft tidak punya nilai historis).
2. Status header di-set ke **"Cancelled"**, field `created_receipts` dikosongkan.
3. `custom_corrugator_qty` pada SO Item/Packed Item terkait dihitung ulang (qty dari dokumen yang dibatalkan ini otomatis tidak lagi terhitung, karena hanya JO Corrugator `docstatus = 1` yang dijumlahkan).

---

## > Penomoran Dokumen

Nomor Job Order Corrugator dibuat otomatis dengan format **`IIB{YY}{NNNN}`**, contoh: `IIB260001`.

- `YY` = 2 digit tahun sesuai Transaction Date
- `NNNN` = nomor urut 4 digit, reset ke 1 setiap pergantian tahun
- Diatur lewat singleton **IIB Document Naming Settings** (counter key: `jop1`)

---

## > Error Umum & Penyebabnya

| Pesan Error | Penyebab | Solusi |
| --- | --- | --- |
| "Items table is empty" | Submit/save tanpa baris item sama sekali | Tambahkan minimal 1 baris item |
| "Row ...: Due Date cannot be before Transaction Date" | Due Date baris lebih awal dari Transaction Date header | Perbaiki tanggal |
| "Row ...: Qty must be positive" | Qty Req diisi 0 atau negatif | Isi qty > 0 |
| "Row ...: Duplicate item ... for Sales Order line ..." | Ada 2 baris dengan kombinasi (Sales Order, Sales Order Item, Item Code) yang sama persis | Hapus salah satu baris duplikat |
| "Row ...: Item ... must be a stock item for Job Order Corrugator" | Item Code yang dipilih bukan stock item | Pakai Item Code lain yang berstatus stock item |
| "Row ...: Item ... has no Stock UOM" | Item Master item terkait belum punya Stock UOM | Lengkapi Stock UOM di Item Master |
| "Row ...: Sales Order Item ... uses UOM ..., but Item ... stock UOM is ..." | UOM di SO Item beda dari Stock UOM item — JO Corrugator tidak mendukung konversi UOM | Perbaiki UOM di Sales Order, atau gunakan item dengan UOM yang sesuai |
| "SO Item ... (item ...): total JO P1 qty ... exceeds packed component SO qty ... + tolerance ... = ..." | Total qty JO Corrugator (dokumen ini + yang sudah submitted sebelumnya) melebihi qty SO + toleransi | Kurangi qty baris ini, atau selesaikan dulu SO tambahan/naikkan qty SO kalau memang perlu produksi lebih banyak |
| "Cannot cancel: submitted Job Order Corrugator Receipts exist for this Job Order Corrugator: ..." | Mencoba cancel JO Corrugator yang Receipt-nya sudah ada yang submitted | Cancel dulu Receipt yang tersebut |
| "Row ...: Sales Order Item ... not found" / "does not belong to ..." | `sales_order_item` di baris rusak/tidak sesuai dengan Sales Order yang dipilih | Kosongkan & pilih ulang Item Code (agar sistem mencari ulang sales_order_item yang benar), atau hapus & tambah ulang baris |

---

## > Dokumen Terkait (Doctype)

- **Job Order Corrugator Item** — child table baris item pada Job Order Corrugator (board spec, machine settings, hasil kalkulasi produksi)
- **Job Order Corrugator Receipt** — dokumen penerimaan hasil produksi corrugator; lihat [`job_order_corrugator_receipt.md`](job_order_corrugator_receipt.md)
- **IIB Settings** — singleton konfigurasi: default Cost Center & Expense Account untuk Receipt, serta tabel toleransi (`IIB Settings Corrugator Tolerance`)
- **Sales Order** / **Sales Order Item** / **Packed Item** — sumber baris item; field `custom_corrugator_qty` di-sync balik oleh JO Corrugator
- **Product Bundle** / **Product Bundle Item** — definisi "Set" yang di-*expand* menjadi baris komponen di JO Corrugator
- **Job Order Corrugator Converting** — proses produksi tahap berikutnya (disebut di `so_batch.md` sebagai salah satu dokumen turunan yang memblokir penghapusan Sales Order)

---

## > Catatan Teknis (untuk tim IT/Developer)

- Lokasi kode: `iib/iib/doctype/job_order_corrugator/job_order_corrugator.py`, client script: `job_order_corrugator.js`
- Nomor dokumen dan sequence dibuat lewat `iib.iib.utils.naming.get_next_iib_number` (counter key `jop1`, 4 digit, reset per tahun — **beda** dari SO Batch/Sales Order yang pakai 5 digit)
- Toleransi dibaca lewat helper bersama `iib.iib.utils.tolerance.lookup_tolerance` (dipakai juga oleh Job Order Corrugator Receipt dan modul Converting/P2)
- Target Warehouse dikunci ke `"Raw Material - IIB"` di level `validate()` (constant `JOP1_TARGET_WAREHOUSE`), tidak bisa diubah user
- Endpoint whitelisted utama:
    - `get_so_items_for_corrugator_dialog` — data untuk dialog "Get Items From → Sales Order" (meng-*expand* Product Bundle ke komponen, membaca `custom_corrugator_qty` dari SO Item/Packed Item)
    - `get_items_from_so_for_corrugator` — dipanggil `map_current_doc` untuk memetakan baris terpilih ke dokumen JO Corrugator baru
    - `get_so_component_items` — search query custom untuk field Item Code di child table (filter ke item Component milik SO baris tsb, termasuk hasil expand bundle)
    - `get_so_item_for_component` — mencari `sales_order_item` yang cocok untuk sebuah Item Code (dipakai client-side saat user pilih Item Code manual)
    - `make_corrugator_receipt` — `get_mapped_doc` untuk tombol Create → Job Order Corrugator Receipt
    - `update_status` — Close/Re-open manual, dibatasi permission `submit`
- Unit test tersedia di `test_job_order_corrugator.py`, namun **saat ini seluruhnya masih `skipTest` (belum diimplementasikan)** — jangan mengandalkan file ini sebagai bukti behavior sudah tervalidasi otomatis
- Rename historis: dulunya disebut "P1"/"JOP1" sebelum di-rename ke "Corrugator" via patch `iib.patches.v0_0.rename_p1_p2_to_corrugator_converting` — nama field internal (`custom_corrugator_qty`, prefix `jop1` di counter key & naming) masih menyisakan singkatan lama, ini normal dan bukan bug

### > Peringatan operasional

- **Jangan jalankan `bench run-tests` di site manapun yang berisi data asli** — termasuk `iib.localhost`. Ini pernah menyebabkan insiden pencemaran data (lihat `erpnext-dev-lessons.md` #58/#63/#66/#67 di workspace `~/Dev/docs/`). Untuk memverifikasi perubahan kode, jalankan test lewat `unittest` di dalam `bench execute` (lihat pola di lesson #67), bukan `bench run-tests`.
- Setelah mengubah `job_order_corrugator.py`, **restart bench** (`bench restart`, atau restart proses `bench start`) sebelum menguji lewat browser — worker yang sedang berjalan tidak otomatis memuat ulang perubahan file Python.

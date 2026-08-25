## Ringkasan

**SO Batch** adalah dokumen custom di sistem ERP (module IIB) yang digunakan untuk membuat banyak **Sales Order** sekaligus dari satu Purchase Order (PO) pelanggan, tanpa perlu input Sales Order satu per satu secara manual.

User cukup memasukkan satu baris per item PO (part number, qty, tanggal kirim, dll), lalu saat dokumen di-**Submit**, sistem otomatis:

1. Mencocokkan Part No ke Item yang benar milik customer tersebut
2. Mengambil harga dari **Master Card** (matrix harga per customer/tier qty)
3. Mengelompokkan baris berdasarkan Jenis PO + PO No + PO Date + Line No
4. Membuat satu Sales Order untuk tiap kelompok tersebut, langsung **Submit**
5. Untuk baris **General**: mencocokkan (matching) qty-nya terhadap stok **FC** yang sudah diproduksi lebih dulu, supaya tim produksi tahu berapa yang tinggal dikirim vs berapa yang masih perlu diproses baru

Dokumen ini bersifat **submittable** (draft → submitted → cancelled), sama seperti Sales Order/Invoice pada umumnya.

---

## Kapan Digunakan

Gunakan SO Batch ketika menerima satu PO dari customer yang berisi **banyak item/line**, dan item-item tersebut perlu dipecah menjadi beberapa Sales Order (misalnya per line number PO, atau per tanggal kirim yang berbeda).

Jika hanya 1 item/line sederhana, tetap bisa dipakai — hasilnya cukup 1 Sales Order.

SO Batch juga dipakai untuk kasus **FC (Forecast)** — saat customer belum mengirim PO resmi tapi produksi sudah harus dimulai lebih dulu. Lihat bagian [Jenis PO](#jenis-po--general-vs-fc) di bawah.

---

## Alur Kerja

### 1. Isi Header

| Field | Keterangan |
| --- | --- |
| **Customer** | Wajib diisi. Menentukan Item & harga yang berlaku (lihat bagian Master Card di bawah) |
| **Transaction Date** | Tanggal transaksi. **Tidak boleh mundur** dari hari ini (tidak bisa backdate) |
| **Company** | Default: PT. Interpak Industries Batam |
| **Currency** & **Conversion Rate** | Mata uang transaksi Sales Order |
| **Terms** (Payment Terms Template) | Wajib diisi |
| **Default Warehouse** | Default: Stores - IIB (tersembunyi di form, terisi otomatis) |

### 2. Isi Tabel "SO Batch Items"

Satu baris = satu item pada PO customer.

| Field | Keterangan |
| --- | --- |
| **Jenis PO** | **General** (default) atau **FC**. Menentukan perilaku PO No/PO Date di baris ini dan apakah baris ini akan mencari kecocokan stok FC saat Sales Order dibuat. Lihat [Jenis PO](#jenis-po--general-vs-fc) |
| **PO No** | Nomor PO customer. Untuk baris **FC**, field ini otomatis dikunci ke `"FC"` — tidak bisa diisi manual, dan nilai `"FC"` **tidak boleh** dipakai untuk baris General (dianggap reserved) |
| **PO Date** | Tanggal PO customer. Untuk baris **FC**, otomatis disamakan dengan Transaction Date |
| **Delivery Date** | Tanggal kirim yang diminta. Tidak boleh sebelum Transaction Date maupun PO Date |
| **Set / Pcs** | Pilih apakah item ini dijual sebagai **Set** (paket/bundle) atau **Pcs** (satuan) |
| **Part No** | Nomor part sesuai PO customer (bukan Item Code internal) |
| **Qty** | Jumlah pesanan. Menentukan tier harga (MOQ) yang dipakai |
| **Line No** | Nomor baris pada PO customer — dipakai untuk mengelompokkan Sales Order |
| **Remark** | Catatan bebas (opsional) — ini berbeda dari field "Remark" hasil matching FC yang muncul di Sales Order Item setelah SO terbentuk (lihat [FC Matching](#fc-matching-fifo)) |
| **Price** | Bisa dikosongkan (sistem akan isi otomatis dari Master Card), atau diisi manual — **harus persis sama** dengan harga sistem, jika tidak akan ditolak |

> Field **Resolved Item Code** dan **Resolved Set Item Code** terisi otomatis oleh sistem, hanya untuk referensi/audit — tidak perlu diisi manual.
>
> Satu SO Batch **boleh berisi campuran** baris Jenis PO General dan FC sekaligus — sistem otomatis memisahkannya menjadi Sales Order yang berbeda (baris FC selalu punya PO No `"FC"`, sehingga tidak pernah tergabung dengan grup General manapun).

### 3. Submit

Saat tombol **Submit** ditekan, sistem menjalankan proses otomatis (lihat "Proses Otomatis Saat Submit" di bawah). Jika semua data valid, Sales Order akan dibuat, **langsung ter-submit**, dan tampil pada tabel **Created Sales Orders** di bagian bawah form (read-only), lengkap dengan link langsung ke tiap SO, customer, tanggal, grand total, dan status.

---

## Proses Otomatis Saat Submit

1. **Validasi Jenis PO** — untuk tiap baris:
    - Jenis PO **FC** → PO No dipaksa `"FC"`, PO Date dipaksa = Transaction Date.
    - Jenis PO **General** → PO No tidak boleh diisi `"FC"` (reserved untuk baris FC).
2. **Resolve Item** — Part No dicocokkan ke Item berdasarkan field `custom_part_no` + `linked_customer` pada Item.
    - Jika **Set**: sistem mencari Product Bundle yang komponennya cocok dan terhubung ke customer tersebut.
    - Jika ditemukan lebih dari satu Item aktif dengan Part No yang sama untuk customer itu → **error** (data Item perlu dibersihkan).
3. **Hitung & Validasi Harga** — harga diambil dari **Master Card** milik customer:
    - Sistem mencari **tier MOQ** tertinggi yang qty-nya ≤ qty pesanan.
    - Untuk item **Set**, harga = jumlah harga tiap komponen dalam bundle × qty komponen.
    - Jika field Price di baris dikosongkan → otomatis diisi harga sistem.
    - Jika Price diisi manual tapi **tidak sama** dengan harga sistem → dokumen ditolak dengan pesan error yang menyebutkan harga yang seharusnya.
4. **Pengelompokan menjadi Sales Order** — baris dikelompokkan berdasarkan kombinasi **(PO No, PO Date, Line No)** — karena PO No baris FC selalu `"FC"`, baris FC dan General tidak pernah tergabung dalam satu grup/SO yang sama. Tiap kelompok unik → 1 Sales Order baru, dengan:
    - Delivery Date SO = tanggal kirim **paling awal** di antara item dalam kelompok tersebut
    - Field `po_no`, `po_date`, `po_line_no`, `po_type` pada SO terisi otomatis
    - Field `so_batch` pada SO diisi dengan nomor SO Batch ini (untuk keterlacakan/trace-back)
5. Setelah SO dibuat, harga pada tiap SO **dikunci ulang** ke harga yang sudah divalidasi (mengatasi kemungkinan ERPNext menghitung ulang harga lewat pricing rule bawaan).
6. Untuk SO berjenis **General**: sistem menjalankan [FC Matching](#fc-matching-fifo) — mencari stok FC yang tersedia dan mengklaimnya.
7. Sales Order **langsung di-Submit** oleh sistem (bukan tersimpan sebagai draft) — user tidak perlu submit manual satu per satu.

Jika SO Batch ini sebelumnya sudah pernah membuat Sales Order (belum dibatalkan), Submit ulang akan **ditolak** — cegah duplikasi SO.

---

## Jenis PO — General vs FC

Ada 2 jenis PO per baris SO Batch Item:

- **General** — kasus normal. Customer sudah punya PO resmi, PO No diisi sesuai dokumen customer.
- **FC (Forecast)** — dipakai kalau customer **belum** punya PO resmi, tapi produksi sudah harus dimulai lebih dulu (SO diwajibkan sebelum proses produksi/Job Order bisa jalan). PO No otomatis `"FC"`.

Saat customer akhirnya mengirim PO resmi, user **tidak perlu mengedit SO FC yang lama** — SO FC itu tetap ada apa adanya sebagai jejak produksi. User cukup buat **SO Batch baru** dengan baris **General** berisi PO No & qty yang sesungguhnya. Sistem otomatis mencocokkan qty General ini terhadap stok FC yang sudah ada (lihat bagian berikut).

---

## FC Matching (FIFO)

Saat Sales Order **General** dibuat (langkah 6 di atas), untuk tiap item di SO tersebut sistem:

1. Menentukan Master Card + Component yang relevan untuk item itu (untuk item **Set**, dicek per komponen di dalam bundle-nya).
2. Mencari semua Sales Order **FC** yang **sudah submitted** dengan Master Card + Component yang sama dan masih ada sisa qty (qty − qty yang sudah diklaim − qty yang sudah delivered).
3. Mengklaim qty tersebut secara **FIFO** — SO FC dengan Transaction Date paling lama diklaim lebih dulu.
4. Mencatat hasilnya:

| Field (di Sales Order Item hasil) | Isi |
| --- | --- |
| **FC Covered Qty** | Jumlah qty yang berhasil ditutup dari stok FC |
| **Remark** | `"Clear"` kalau seluruh qty General sudah tertutup FC (tidak perlu produksi baru), atau `"Ord. {sisa}"` kalau sebagian masih perlu produksi baru — angka `{sisa}` = qty General − qty yang tertutup FC, ditulis dengan pemisah ribuan (mis. `"Ord. 29,200"`) |
| **FC Matched Qty** (di SO FC sumbernya) | Akumulasi qty yang sudah diklaim dari SO FC tersebut oleh SO General manapun |

> SO FC hanya diikutsertakan pencarian kalau **sudah di-Submit** — SO FC yang masih draft (jarang terjadi karena sekarang auto-submit) tidak dihitung, supaya qty yang dijanjikan tidak berubah-ubah.

### Auto-Close SO FC yang sudah penuh tertutup

Begitu **seluruh** qty pada sebuah SO FC sudah diklaim oleh SO General (baik dari satu maupun beberapa SO General), SO FC tersebut **otomatis di-Close** (status "Closed") — menandakan tidak ada lagi yang perlu ditunggu/diproses untuk SO itu.

Kalau kemudian klaim tersebut **dilepas kembali** (misalnya SO General yang mengklaimnya dibatalkan — lihat [Pembatalan](#pembatalan-cancel)) sehingga SO FC itu jadi tidak lagi tertutup penuh, sistem otomatis **membuka kembali** status Closed-nya.

---

## Pembatalan (Cancel)

Jika SO Batch dibatalkan:

- Semua Sales Order yang dibuat dari batch ini ikut diproses:
    - Jika SO sudah **submitted** → di-**cancel** (kalau statusnya "Closed", dibuka dulu — ERPNext tidak mengizinkan cancel langsung atas SO yang Closed)
    - Jika SO masih **draft** → langsung **dihapus**
- Kalau SO yang dibatalkan itu berjenis **General** dan sempat mengklaim qty FC, klaim tersebut **dilepas kembali** ke SO FC sumbernya (qty FC jadi tersedia lagi untuk SO lain)
- Kalau SO yang dibatalkan itu berjenis **FC** dan qty-nya **sudah diklaim** oleh SO General lain (di luar batch yang sedang dibatalkan ini), pembatalan **ditolak** — harus selesaikan/batalkan dulu SO General yang mengklaimnya
- Tabel "Created Sales Orders" dikosongkan kembali

> Kalau satu SO Batch berisi campuran FC + General dan General-nya sempat mengklaim FC dari batch yang sama, urutan di atas ditangani otomatis (pelepasan klaim jalan lebih dulu sebelum pengecekan blokir), jadi batch campuran tetap bisa dibatalkan dengan aman.

---

## Penghapusan (Delete)

Sales Order dan SO Batch saling terhubung (SO punya field `so_batch`, SO Batch punya tabel referensi ke SO-nya) — kalau dihapus lewat urutan yang salah, Frappe akan menolak keduanya karena masih saling terkait.

Alur yang benar:

1. **Cancel SO Batch dulu** (seperti biasa, lihat di atas)
2. **Delete SO Batch** — Sales Order yang terhubung **otomatis ikut terhapus**, tidak perlu hapus manual

Sebelum benar-benar menghapus, sistem memeriksa:

- FC yang masih diklaim SO lain → penghapusan ditolak (sama seperti aturan cancel di atas)
- SO yang sudah punya **Delivery Note / Sales Invoice / Job Order Corrugator / Job Order Converting** yang menunjuk ke dia → penghapusan ditolak, supaya dokumen turunan tersebut tidak menunjuk ke SO yang sudah tidak ada. Selesaikan/hapus dokumen turunan tersebut dulu.

---

## Blokir Delivery Note & Sales Invoice untuk SO yang Masih FC

Selama sebuah Sales Order masih berjenis **FC** (belum ada PO resmi dari customer), sistem **menolak** pembuatan Delivery Note maupun Sales Invoice yang mengacu ke SO tersebut, dengan pesan:

> "Cannot proceed: Sales Order {nama} is still Jenis PO = FC. Wait for the customer's PO Number before creating a Delivery Note / Sales Invoice."

Produksi (Job Order Corrugator/Converting) **tetap diizinkan** untuk SO FC — itu memang tujuan utamanya, supaya produksi bisa mulai lebih awal sebelum PO resmi turun.

---

## Penomoran Dokumen

Nomor SO Batch dibuat otomatis dengan format **`YYNNNNN`**, contoh: `2600001`.

- `YY` = 2 digit tahun sesuai Transaction Date
- `NNNNN` = nomor urut 5 digit, reset ke 1 setiap pergantian tahun
- Diatur lewat singleton **IIB Document Naming Settings** (counter key: `so_batch`)

Sales Order yang dihasilkan memakai nomor urut yang sama (`counter key: sales_order`), terlepas dari Jenis PO-nya — General dan FC berbagi seri penomoran yang sama, dibedakan lewat field `po_type`, bukan lewat prefix nomor.

---

## Error Umum & Penyebabnya

| Pesan Error | Penyebab | Solusi |
| --- | --- | --- |
| "Transaction Date cannot be backdated" | Tanggal transaksi < hari ini | Ubah ke tanggal hari ini atau lebih baru |
| "Delivery Date cannot be before Transaction Date/PO Date" | Delivery Date lebih awal dari tanggal lain | Perbaiki tanggal kirim |
| "PO No 'FC' is reserved for Jenis PO = FC" | Baris General diisi PO No `"FC"` | Ganti PO No, nilai `"FC"` hanya untuk baris berjenis FC |
| "No active Item found with Part No ... for customer ..." | Part No belum terdaftar sebagai Item untuk customer tsb | Cek/lengkapi data Item (`custom_part_no`, `linked_customer`) |
| "Multiple active Items found with Part No ..." | Ada duplikasi Item dengan Part No sama untuk 1 customer | Nonaktifkan/perbaiki salah satu Item |
| "No Product Bundle item for Part No ... belongs to customer ..." | Item dipilih sebagai Set tapi tidak ada Product Bundle yang valid | Cek konfigurasi Product Bundle & Master Card |
| "Rate ... does not match system price ..." | Price diisi manual tapi tidak sama dengan harga Master Card | Kosongkan Price agar terisi otomatis, atau samakan dengan harga yang ditampilkan di error |
| "No Master Card price found for ... at qty ..." | Tidak ada tier MOQ pada Master Card yang mencakup qty tsb | Lengkapi tier harga di Master Card, atau sesuaikan qty |
| "Sales Orders already exist for this SO Batch" | SO Batch ini sudah pernah submit & membuat SO | Batalkan (cancel) SO Batch dulu sebelum submit ulang |
| "Sales Order ... (FC) already has quantity claimed by a later PO" | Mencoba cancel/hapus SO FC yang qty-nya sudah diklaim SO General lain | Selesaikan/batalkan dulu SO General yang mengklaimnya |
| "Cannot proceed: Sales Order ... is still Jenis PO = FC" | Mencoba buat Delivery Note/Sales Invoice untuk SO yang masih FC | Tunggu PO resmi dari customer, buat SO Batch General baru dulu |
| "Cannot delete Sales Order ...: still referenced by ..." | Mencoba hapus SO Batch yang SO-nya sudah punya Delivery Note/Sales Invoice/Job Order | Selesaikan/hapus dokumen turunan tersebut dulu |

---

## Dokumen Terkait (Doctype)

- **SO Batch Item** — child table baris item pada SO Batch (termasuk field `po_type`)
- **SO Batch Created SO** — child table hasil (link ke Sales Order yang terbentuk)
- **FC Match Log** — audit trail tiap klaim FC→General: SO FC sumber, SO General konsumen, Master Card, Component, qty yang diklaim. Dipakai untuk melepas klaim secara akurat saat SO General dibatalkan
- **Master Card** — sumber data harga (tier MOQ per component)
- **Product Bundle** — definisi paket/"Set" dan komponen-komponennya
- **Sales Order** — dokumen akhir yang dihasilkan (field `so_batch` menyimpan referensi balik ke SO Batch ini; field `po_type` menyimpan Jenis PO)

---

## Catatan Teknis (untuk tim IT/Developer)

- Lokasi kode: `iib/iib/doctype/so_batch/so_batch.py`
- Custom fields (Sales Order, Sales Order Item, Packed Item) diinstal lewat patch `iib/patches/v1_0/add_po_type_fields.py`:
    - `Sales Order.po_type`
    - `Sales Order Item` / `Packed Item`: `custom_po_type`, `custom_master_card`, `custom_component` (internal, hidden — dipakai mesin matching), `custom_fc_matched_qty` (di Sales Order Item: tampil di grid; di Packed Item: hidden), `custom_fc_covered_qty` (label "FC Covered Qty"), `custom_fc_coverage_note` (label "Remark")
- Tidak ada custom client script tambahan untuk logika bisnis inti (form pakai perilaku standar Frappe) — `so_batch.js` hanya mengisi otomatis PO No/PO Date saat baris diset Jenis PO = FC (UX saja, validasi sesungguhnya tetap di server)
- Sales Order dan Delivery Note diberi hook `validate` (`block_fc_sales_orders`) untuk memblokir dokumen turunan terhadap SO yang masih FC; Sales Invoice memakai hook yang sama
- Unit test tersedia di `test_so_batch.py` (mencakup validasi rate, perhitungan harga Set, pemilihan tier MOQ, validasi Jenis PO, FIFO matching, auto-close/reopen, dan pengecekan dokumen turunan sebelum delete)
- Hook `set_dn_po_line_no` menyalin `po_line_no` dari Sales Order ke Delivery Note Item saat Delivery Note dibuat dari SO tersebut

### Peringatan operasional

- **Jangan jalankan `bench run-tests` di site manapun yang berisi data asli** — termasuk `iib.localhost`. Ini pernah menyebabkan insiden pencemaran data (lihat `erpnext-dev-lessons.md` #58/#63/#66/#67 di workspace `~/Dev/docs/`). Untuk memverifikasi perubahan kode, jalankan test lewat `unittest` di dalam `bench execute` (lihat pola di lesson #67), bukan `bench run-tests`.
- Setelah mengubah `so_batch.py`, **restart bench** (`bench restart`, atau restart proses `bench start`) sebelum menguji lewat browser — worker yang sedang berjalan tidak otomatis memuat ulang perubahan file Python.

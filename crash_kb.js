(function (g) {
  const CAPS = {
    AddAtomicModel: 14000,
    AddDamageAtomicModel: 70,
    AddTimeModel: 169,
    AddClumpModel: 5,
    AddPedModel: 130,
    AddVehicleModel: 110,
    AddWeaponModel: 37
  };

  const OFFSETS = [
    [0x45C2AC, 'CModelInfo::AddAtomicModel'],
    [0x5547BC, 'CFileLoader::LoadObject'],
    [0x5525AC, 'CFileLoader::LoadObjectTypes'],
    [0x551CEC, 'CFileLoader::LoadLevel'],
    [0x4D5A70, 'CGame::Initialise'],
    [0x4D93F4, 'InitialiseGame'],
    [0x70A208, 'DoGameState'],
    [0x70ABB0, 'MainGameFunc'],
    [0x70AF48, 'OS_ApplicationTick']
  ];

  const KB = [];
  const add = function (o) { KB.push(o); };

  add({
    id: 'model-pool', base: 0.92,
    fn: /CModelInfo::Add\w*Model/,
    title: 'Kapasitas penyimpanan model (ModelInfo) penuh atau ID model bermasalah',
    c: [
      'Game sedang mendaftarkan model baru dari baris IDE. Penyimpanan untuk tipe model itu sudah habis, sehingga alokasi mengembalikan null dan game menulis ke null + offset kecil. Ini cocok dengan alamat error yang sangat kecil.',
      'Penyebab umum: terlalu banyak mod penambah objek, kendaraan, ped atau senjata (paket map, mod loader), ID model ganda, atau ID di luar rentang 0-19999.',
      'Batas bawaan game per tipe: atomic 14000, damage atomic 70, time 169, clump 5, ped 130, vehicle 110, weapon 37.'
    ],
    f: [
      'Kurangi atau lepas mod penambah model. Uji dengan memindahkan mod dari ZyZ ModLoader, XkiLoader dan mod map satu per satu.',
      'Pastikan limit adjuster yang cocok untuk game 64-bit aktif dan batas jumlah model/IDE-nya dinaikkan. Jangan memasang beberapa limit adjuster yang mengubah batas yang sama.',
      'Periksa IDE mod: tidak ada ID duplikat, semua ID unik dan di bawah 20000, jumlah kolom tiap baris sesuai tipe (objs, tobj, cars, ped, weap).',
      'Jika crash muncul setelah menambah satu mod, pindahkan mod itu dan coba lagi.'
    ],
    mods: /Loader|Limit|ModelExtras|VehFuncs|Map|Vehicle|Ped/i,
    strings: true,
    extra: function (c) {
      const ev = [];
      let bonus = 0;
      const m = /Add(\w+?)Model/.exec(c.top);
      const cap = m && CAPS['Add' + m[1] + 'Model'];
      if (cap) {
        Object.keys(c.p.regs).forEach(function (k) {
          const v = c.p.regs[k].dec;
          if (v === cap || v === cap + 1) {
            ev.push(c.en ? k + ' = ' + v + ' equals the storage capacity of this model type (' + cap + ')' : k + ' = ' + v + ' sama dengan kapasitas penyimpanan model tipe ini (' + cap + ')');
            bonus = 0.04;
          }
        });
      }
      const x0 = c.p.regs.X0;
      if (x0 && x0.dec >= 0 && x0.dec < 100000) {
        ev.push('X0 = ' + x0.dec + ' (0x' + x0.dec.toString(16).toUpperCase() + ')' + (c.en ? ', probably the model ID being registered' + (x0.dec >= 20000 ? ', outside the valid ID range 0-19999' : '') : ', kemungkinan ID model yang sedang didaftarkan' + (x0.dec >= 20000 ? ', di luar batas ID 0-19999' : '')));
      }
      return { bonus: bonus, ev: ev };
    }
  });

  add({
    id: 'ide-load', base: 0.55,
    fn: /CFileLoader::Load(Object|ObjectTypes|Level|Vehicle|Ped|Weapon|TimeObject|Clump|2dfx|Path|Atomic)/,
    title: 'Crash saat membaca file IDE/DAT (pemuatan level di awal game)',
    c: [
      'Crash terjadi saat game memuat daftar objek dari gta.dat dan IDE, jadi pemicunya hampir selalu data mod dan bukan aksi pemain.',
      'Baris IDE salah format, jumlah kolom salah, nama model atau TXD ganda, atau file IDE/DAT rusak.'
    ],
    f: [
      'Periksa mod yang baru ditambah: file IDE, gta.dat/default.dat dan folder mod loader.',
      'Simpan file data sebagai teks biasa (UTF-8 tanpa BOM) dengan akhir baris konsisten.',
      'Cari nama model pada bagian bukti di semua file .ide untuk menemukan mod pelakunya.',
      'Pindahkan mod penambah objek secara bergantian (metode bagi dua) sampai game bisa jalan.'
    ],
    mods: /Loader|Map|Limit/i,
    strings: true
  });

  add({
    id: 'ipl-load', base: 0.55,
    fn: /CFileLoader::Load(ObjectInstance|Scene|CarGenerator|EntityInstance|Zone|Occlusion)|CIplStore::|CPools?::/,
    title: 'Crash saat membaca IPL / instance objek',
    c: [
      'IPL memakai ID model yang tidak ada di IDE, atau jumlah instance melebihi pool (Building, Dummy, Object, PtrNode).',
      'File IPL streaming (biner) rusak atau tidak sesuai dengan isi IMG.'
    ],
    f: [
      'Pastikan semua ID di IPL terdaftar di IDE. Periksa mod map yang terakhir dipasang.',
      'Naikkan pool terkait lewat limit adjuster.',
      'Pasang ulang IPL/IMG mod map dari sumber aslinya.'
    ],
    mods: /Map|Limit|Loader/i
  });

  add({
    id: 'streaming', base: 0.6,
    fn: /CStreaming::|CdStream|CStreamingInfo|RequestModel|LoadRequestedModels|ConvertBufferToObject/,
    title: 'Masalah streaming model / arsip IMG',
    c: [
      'Model yang diminta tidak ada, ukuran entri IMG salah, atau arsip IMG rusak atau terpotong akibat salinan tidak lengkap.',
      'Memori streaming habis karena tekstur atau model HD terlalu banyak.'
    ],
    f: [
      'Periksa ukuran dan keutuhan gta3.img serta IMG mod, lalu salin ulang.',
      'Naikkan batas memori streaming secukupnya. Jangan berlebihan pada HP dengan RAM kecil.',
      'Hapus model/DFF mod yang baru ditambahkan.'
    ],
    mods: /Limit|Advanced|Settings|Loader/i
  });

  add({
    id: 'txd', base: 0.6,
    fn: /CTxdStore|RwTexture|RwTexDictionary|RwRaster|TextureDatabase|TextureDictionary/,
    title: 'TXD / tekstur bermasalah',
    c: [
      'TXD rusak, format tekstur tidak didukung GPU, atau resolusi terlalu besar sehingga alokasi raster gagal.',
      'Parent TXD tidak ada atau nama tekstur bentrok antar TXD.'
    ],
    f: [
      'Gunakan format tekstur yang cocok dengan paket game Android (DXT/PVR/ETC) dan hindari resolusi sangat besar.',
      'Kompres atau perkecil tekstur mod. Cek nama tekstur yang dipakai DFF.',
      'Kembalikan TXD original untuk memastikan TXD mana yang menjadi pelaku.'
    ]
  });

  add({
    id: 'dff', base: 0.6,
    fn: /RpClump|RpAtomic|RpGeometry|RwStream|RwFrame|CClumpModelInfo|CVehicleModelInfo::(SetClump|SetAtomicRenderCallbacks|PreprocessHierarchy|SetEditableMaterials|SetVehicleComponentFlags)|CBaseModelInfo::(SetClump|AddTexDictionaryRef)|CAtomicModelInfo::/,
    title: 'DFF / geometri model rusak',
    c: [
      'DFF rusak atau memakai versi RenderWare yang salah, geometri kosong, atau frame dan dummy wajib (chassis, wheel_*_dummy) tidak ada.',
      'Skin atau bone tidak cocok dengan skeleton ped, atau jumlah material terlalu banyak.'
    ],
    f: [
      'Ekspor ulang DFF dengan versi RenderWare GTA SA dan nama frame standar.',
      'Pastikan kendaraan punya frame wajib.',
      'Ganti model mod dengan model original untuk memastikan DFF pelakunya.'
    ],
    mods: /ModelExtras|VehFuncs|Tuning|Weapon|Rolling|Deform|Damage/i
  });

  add({
    id: 'vehicle', base: 0.5,
    fn: /CVehicle::|CAutomobile::|CBike::|CCarCtrl::|CHandlingDataMgr|CVehicleModelInfo::|CTrain::|CHeli::|CPlane::|CBoat::|CCarGenerator|CStoredCar/,
    title: 'Masalah kendaraan (handling, model atau spawn)',
    c: [
      'handling.cfg, vehicles.ide, carcols atau carmods tidak lengkap untuk kendaraan mod, atau dummy dan komponen model hilang.',
      'Mod yang mengubah kendaraan (tuning, deform, siren, ModelExtras) memakai data yang tidak tersedia di kendaraan tertentu.'
    ],
    f: [
      'Pastikan tiap kendaraan mod punya handling ID, entri handling.cfg, carcols dan vehicles.ide yang benar.',
      'Nonaktifkan sementara mod kendaraan (BeamNG Damage, Tuning, VSL, ModelExtras) lalu aktifkan satu per satu.',
      'Uji kendaraan yang sama sendirian untuk memastikan modelnya.'
    ],
    mods: /BeamNG|Damage|Tuning|VSL|Siren|ModelExtras|VehFuncs|Train|Contrail|OilLeak|Rolling|Headlights/i
  });

  add({
    id: 'ped-anim', base: 0.5,
    fn: /CPed::|CPlayerPed|CPedModelInfo|CAnimManager|CAnimBlend|CTask|CPedIntelligence|CPedDamage|CClothes|CPedClothes/,
    title: 'Masalah ped / animasi',
    c: [
      'Animasi (IFP) atau blok animasi tidak termuat atau tidak cocok dengan skeleton ped. ped.ifp bisa rusak, atau mod animasi dan combat tidak cocok.',
      'Ped mod tidak punya entri pedstats atau pedgrp, atau modelnya belum selesai di-stream saat dipakai.'
    ],
    f: [
      'Kembalikan ped.ifp dan IFP original lalu uji.',
      'Nonaktifkan mod animasi dan pertarungan (FightBlock, PCScreenGesture, Rolling, Advanced Aiming).',
      'Pastikan ped mod punya entri IDE, pedstats dan pedgrp yang benar.'
    ],
    mods: /FightBlock|Gesture|Rolling|Anim|Aiming|Ped/i
  });

  add({
    id: 'weapon', base: 0.5,
    fn: /CWeapon::|CWeaponInfo|CWeaponEffects|CBulletInfo|CBulletTrace|CWeaponModelInfo|CShotInfo|CProjectile/,
    title: 'Masalah senjata',
    c: [
      'weapon.dat memiliki kolom yang kurang atau lebih, atau ID senjata tidak ada. Model senjata belum termuat.',
      'Mod senjata, tracer atau aim yang meng-hook fungsi tembak tidak cocok dengan senjata mod.'
    ],
    f: [
      'Periksa weapon.dat dan IDE senjata mod.',
      'Nonaktifkan mod BulletTracers, Advanced Aiming, GrenadeAim, Weapon Details dan Weapon On Player secara bergantian.',
      'Kembalikan weapon.dat original untuk uji.'
    ],
    mods: /Weapon|Bullet|Tracer|Aim|Grenade/i
  });

  add({
    id: 'fx', base: 0.55,
    fn: /Fx[A-Z]|CParticle|CFx|FxPrim|FxEmitter/,
    title: 'Masalah efek partikel (FX)',
    c: [
      'File efek (.fxp) rusak atau melebihi batas FX, terutama saat banyak mod efek aktif (api, asap, jejak, kontrail, bocor oli).',
      'Nama efek tidak ditemukan.'
    ],
    f: [
      'Naikkan batas lewat FxLimitAdjuster dan kurangi efek mod.',
      'Nonaktifkan mod efek (ClassicFX, Plane Contrail, OilLeak) untuk uji.',
      'Kembalikan effects.fxp original.'
    ],
    mods: /Fx|Contrail|Oil|Classic|Effect/i
  });

  add({
    id: 'audio', base: 0.5,
    fn: /CAE|CAudio|BASS|BankLoad|SFX|AudioTrack|OpenSL/,
    lib: /libBASS|libOpenSLES|libaudio/,
    title: 'Masalah audio',
    c: [
      'File audio mod (mp3, wav, ogg atau bank SFX) rusak atau formatnya tidak didukung, atau thread audio dan BASS mengalami race.',
      'Mod audio atau radio yang tidak cocok dengan versi BASS Sound Library.'
    ],
    f: [
      'Pindahkan mod audio dan radio, lalu uji.',
      'Perbarui BASS Sound Library dan mod yang bergantung padanya.',
      'Konversi audio ke format standar.'
    ],
    mods: /BASS|Sound|Audio|Radio/i
  });

  add({
    id: 'gpu', base: 0.7,
    lib: /libGLES|libEGL|libmali|adreno|libgsl|libllvm-glnext|libvulkan|libPVR/i,
    title: 'Crash di driver GPU / grafis',
    c: [
      'Crash terjadi di driver GPU, biasanya karena tekstur, shader atau framebuffer tidak valid, memori GPU habis, atau bug driver pada efek post-processing.'
    ],
    f: [
      'Turunkan resolusi dan kualitas tekstur, matikan efek shader dan post-processing (ClassicFX, Project 2DFX, mod visual).',
      'Perbarui sistem perangkat dan tutup aplikasi lain.',
      'Uji di perangkat lain bila memungkinkan.'
    ],
    mods: /Classic|2DFX|Shader|Graphics|Visual/i
  });

  add({
    id: 'libc', base: 0.5,
    lib: /^(libc\.so|libc\+\+|libm\.so|libdl\.so)/,
    title: 'Crash di fungsi pustaka C (memori/string)',
    c: [
      'Fungsi salin atau baca string dan memori menerima pointer tidak valid dari pemanggilnya: pointer null, string tanpa akhiran null, atau buffer yang sudah dibebaskan.'
    ],
    f: [
      'Lihat pemanggil pada rantai di bagian bukti. Itulah kode yang sebenarnya bermasalah.',
      'Jika pemanggilnya mod, perbarui atau hapus mod itu.',
      'Pastikan file data yang dibaca (txt, dat, ide, cfg) tidak kosong atau rusak.'
    ]
  });

  add({
    id: 'abort', base: 0.6,
    sig: /SIGABRT/,
    fn: /\babort\b|__libc_fatal|__cxa_throw|std::terminate/,
    title: 'Game menghentikan dirinya sendiri (abort / exception)',
    c: [
      'SIGABRT berarti program memanggil abort. Penyebabnya biasanya exception C++ yang tidak tertangani (misalnya bad_alloc karena memori habis), assert, atau deteksi kerusakan heap seperti double free atau buffer overflow.'
    ],
    f: [
      'Tutup aplikasi lain dan kurangi mod yang memakai memori besar (tekstur HD, banyak kendaraan).',
      'Hapus mod yang baru dipasang lalu uji ulang.',
      'Jika crash berpindah-pindah lokasi, curigai kerusakan heap oleh mod yang meng-hook memori.'
    ]
  });

  add({
    id: 'sigbus', base: 0.7, sig: /SIGBUS/,
    title: 'Akses memori tidak sejajar atau file ter-map terpotong (SIGBUS)',
    c: [
      'SIGBUS muncul pada akses tidak sejajar atau saat file yang di-map ke memori terpotong atau hilang, misalnya OBB atau IMG yang berubah saat game berjalan atau penyimpanan yang terlepas.'
    ],
    f: [
      'Salin ulang OBB dan data game, pastikan penyimpanan cukup dan stabil.',
      'Jangan memindah atau mengubah file game saat game berjalan.'
    ]
  });

  add({
    id: 'sigfpe', base: 0.8, sig: /SIGFPE/,
    title: 'Pembagian dengan nol (SIGFPE)',
    c: [
      'Ada perhitungan yang membagi dengan nol, biasanya karena nilai 0 pada data (massa atau ukuran di handling.cfg, parameter efek atau konfigurasi mod).'
    ],
    f: [
      'Periksa handling.cfg dan konfigurasi mod yang baru diubah.',
      'Kembalikan nilai ke default dan uji.'
    ]
  });

  add({
    id: 'sigill', base: 0.7, sig: /SIGILL|SIGTRAP/,
    title: 'Instruksi ilegal / patch mod salah (SIGILL atau SIGTRAP)',
    c: [
      'CPU mengeksekusi data atau instruksi tidak valid. Penyebab umum: patch atau hook mod menulis ke alamat yang salah karena versi game tidak cocok, atau mod 32-bit dipakai pada game 64-bit.'
    ],
    f: [
      'Pastikan semua mod berarsitektur sama dengan game (arm64) dan versi game didukung mod.',
      'Perbarui mod, lalu pindahkan satu per satu untuk mencari pelaku.'
    ]
  });

  add({
    id: 'init', base: 0.3,
    fn: /CGame::Initialise|InitialiseGame|CGame::InitialiseOnceAfterRW|CGame::InitialiseRenderWare/,
    title: 'Crash saat inisialisasi game (sebelum menu)',
    c: [
      'Crash terjadi sebelum game sampai ke menu, sehingga penyebabnya biasanya file data mod atau konflik mod saat dimuat, bukan gameplay.'
    ],
    f: [
      'Pindahkan semua mod, lalu kembalikan beberapa sekaligus (metode bagi dua) sampai crash muncul lagi.',
      'Setelah menemukan kelompok pelaku, persempit sampai satu mod.'
    ]
  });

  add({
    id: 'save', base: 0.6,
    fn: /CGenericGameStorage|GenericLoad|LoadSaveGame|CRestart::|CSaveGame/,
    title: 'Masalah save game',
    c: [
      'Save berisi data model atau kendaraan dari mod yang sekarang tidak terpasang, atau file save rusak.'
    ],
    f: [
      'Pasang kembali mod yang dipakai saat save dibuat.',
      'Coba slot save lain atau backup, dan jangan menimpa file save yang rusak.'
    ]
  });

  add({
    id: 'gxt', base: 0.5,
    fn: /CText::|CMessages::|CTextManager|CKeyArray/,
    title: 'Masalah teks (GXT)',
    c: [
      'File GXT rusak, kunci teks tidak ditemukan, atau mod teks tidak cocok dengan bahasa game.'
    ],
    f: [
      'Kembalikan file GXT original dan pasang ulang mod teks yang cocok dengan versi game.'
    ]
  });

  add({
    id: 'script', base: 0.55,
    fn: /CRunningScript|CTheScripts|CStreamedScripts|ScriptCommand|CLEO/,
    title: 'Masalah script (main.scm / CLEO)',
    c: [
      'Script memakai perintah atau ID model yang tidak ada, atau main.scm tidak cocok dengan mod yang terpasang.'
    ],
    f: [
      'Nonaktifkan script mod terakhir yang dipasang.',
      'Pastikan mod berbasis script mendukung versi game yang dipakai.'
    ]
  });

  add({
    id: 'ui', base: 0.35,
    fn: /CHud::|CMenuManager|CRadar::|CWidget|CTouchInterface|CFont::|CSprite2d/,
    title: 'Masalah HUD / menu / radar / kontrol layar',
    c: [
      'Tekstur atau data HUD tidak ditemukan, atau mod menu, radar dan kontrol layar bentrok dengan layout bawaan.'
    ],
    f: [
      'Nonaktifkan mod tampilan (PC Menu, GPS, Wanted Radar, mod HUD) lalu uji.',
      'Kembalikan file HUD dan tekstur original.'
    ],
    mods: /Menu|Radar|HUD|Gesture|GPS|Wanted/i
  });

  add({
    id: 'collision', base: 0.5,
    fn: /CCollision|CColModel|CColStore|CPhysical::|CColAccel/,
    title: 'Masalah collision',
    c: [
      'File COL rusak atau model tidak memiliki collision yang valid, atau terjadi kesalahan di pemeriksaan fisika.'
    ],
    f: [
      'Pastikan model baru punya COL valid. Pasang ulang COL mod.',
      'Nonaktifkan mod fisika dan damage (BeamNG Damage) untuk uji.'
    ],
    mods: /Damage|Deform|Physics/i
  });

  add({
    id: 'world', base: 0.4,
    fn: /CRenderer::|CEntity::(Render|Add|Remove|PreRender|UpdateRwFrame)|CBuilding|CObject::|CDummy|CWorld::|CShadows|CCoronas|CPointLights|CWaterLevel|CTimeCycle|CWeather/,
    title: 'Masalah dunia / rendering (entity, bayangan, cahaya, cuaca)',
    c: [
      'Entity atau model tidak lengkap saat dirender, atau terjadi kesalahan pada bayangan, korona, lampu, air atau timecyc.',
      'Mod LOD, 2DFX, siren dan lampu dapat melebihi batas internal.'
    ],
    f: [
      'Nonaktifkan Project 2DFX, VSL dan mod lampu atau visual lain secara bergantian.',
      'Pastikan timecyc.dat, water.dat dan IPL tidak diubah ke format yang salah.'
    ],
    mods: /2DFX|VSL|Siren|Headlights|Classic|Shadow|Light/i
  });

  add({
    id: 'recursion', base: 0.6,
    when: function (c) {
      const counts = {};
      let max = 0;
      c.funcs.forEach(function (f) { if (f) { counts[f] = (counts[f] || 0) + 1; if (counts[f] > max) max = counts[f]; } });
      return max >= 8 || c.funcs.length >= 60 ? { score: 0.6 } : 0;
    },
    title: 'Rekursi tak berujung / stack overflow',
    c: [
      'Fungsi yang sama berulang sangat banyak pada rantai pemanggil. Ini tanda rekursi tanpa henti atau dua hook yang saling memanggil.'
    ],
    f: [
      'Cari dua mod yang meng-hook fungsi yang sama dan nonaktifkan salah satunya.',
      'Perbarui mod yang terlibat.'
    ]
  });

  add({
    id: 'mod-crash', base: 0.85,
    when: function (c) {
      const i = c.frames.slice(0, 3).findIndex(function (f) { return f.isMod; });
      if (i < 0) return 0;
      return { score: i === 0 ? 0.85 : 0.6, hit: c.frames[i].lib };
    },
    title: 'Crash berasal langsung dari kode sebuah mod',
    c: [
      'Frame teratas pada rantai berada di dalam file mod, bukan di kode asli game. Pelaku paling mungkin adalah mod itu sendiri atau data yang dibacanya.'
    ],
    f: [
      'Perbarui mod ke versi terbaru dan pastikan cocok dengan versi game serta arsitektur perangkat.',
      'Hapus mod beserta file konfigurasinya, lalu pasang ulang secara bersih.',
      'Laporkan ke pembuat mod dengan melampirkan aml_crashlog.txt utuh.'
    ]
  });

  const FAULT = {
    'null': {
      title: 'Akses pointer null atau indeks negatif',
      c: ['Alamat error sangat kecil, artinya game membaca atau menulis anggota struct atau array lewat pointer null. Pointer null biasanya muncul karena data yang dicari tidak ditemukan (model, TXD, animasi, handling) atau penyimpanan (pool) sudah penuh.'],
      f: ['Cocokkan fungsi pelaku pada rantai dengan kategori di atas.', 'Ingat perubahan terakhir sebelum crash: mod baru atau file yang diganti.'],
      s: 0.3
    },
    neg: {
      title: 'Indeks atau nilai -1 dipakai sebagai alamat',
      c: ['Alamat error berupa angka sangat besar yang berasal dari nilai negatif. Biasanya ID atau indeks bernilai -1 (tidak ditemukan) dipakai langsung sebagai indeks array.'],
      f: ['Cari data referensi yang hilang: ID model, nama TXD atau animasi yang tidak terdaftar.'],
      s: 0.3
    },
    pattern: {
      title: 'Alamat error berpola (memori tidak diinisialisasi atau sudah dibebaskan)',
      c: ['Alamat error berupa pola khas (misalnya 0x7F7F7F7F, DEADBEEF) yang menandakan memori belum diinisialisasi atau sudah dibebaskan.'],
      f: ['Curigai mod yang meng-hook memori atau objek yang sudah dihapus. Nonaktifkan mod terbaru.'],
      s: 0.3
    },
    prot: {
      title: 'Menulis ke memori yang dilindungi (SEGV_ACCERR)',
      c: ['Kode mencoba menulis ke area read-only, misalnya patch pada kode atau data tanpa mengubah izin memori, atau alamat patch salah karena versi game tidak cocok.'],
      f: ['Pastikan mod yang melakukan patch kompatibel dengan versi game.', 'Perbarui atau pindahkan mod patching terbaru.'],
      s: 0.3
    },
    wild: {
      title: 'Pointer liar (alamat tidak valid)',
      c: ['Game mengakses alamat yang tidak dipetakan. Penyebab umum: pointer rusak karena memori tertimpa, objek yang sudah dihapus, atau data file yang salah.'],
      f: ['Lihat rantai pemanggil, lalu uji dengan melepas mod yang baru dipasang.'],
      s: 0.2
    }
  };

  g.CRASH_KB = { rules: KB, caps: CAPS, offsets: OFFSETS, fault: FAULT };
})(typeof window !== 'undefined' ? window : globalThis);

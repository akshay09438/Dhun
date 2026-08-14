"""GENERATED — do not edit by hand. Run `scripts/generate_marks.py` to rebuild.

The founder's ear-marks from `scripts/song_marks.csv`, re-keyed from filename to the song's content
id so a rename cannot detach a song from its marks.

This table is a FALLBACK ONLY. `planner/hooks.py` and `planner/main_drops.py` hold the hand-marked,
ear-confirmed entries and are consulted FIRST; a song appearing there is deliberately absent here.
That ordering is what lets this file be regenerated safely — it can never retune a song that is
already working. See `tests/test_marks_generated.py`.

Built from 410 marks across 178 files:
133 of those songs are in the catalog, 27 already carry a
hand-mark (left alone), 45 are for songs the app has never loaded.
"""

from __future__ import annotations

# song content id -> (hook_start_secs, hook_end_secs) on the song's own native timeline.
GEN_HOOKS: dict[str, tuple[float, float]] = {
    # abcdefu (GAYLE)
    "f90c50e5f3e5dedc60fd01225a5257bd870a28452c8f0f9beb0ebfe3ed1680a5": (69.1, 89.58),
    # All The Stars (Kendrick Lamar, SZA)
    "0c3ba845896f89d854b28dc8c094697b3c6933b8a7cd0a46840e38299f4a9542": (40.39, 59.61),
    # Anchor Point (Ahmed Spins)
    "2c17fc64b6928f0499a306402b676bc62e3118588e42494c8ec7063a7a948267": (85.27, 99.17),
    # Animals (Martin Garrix)
    "6bbf744033c9d61a7c15fa2a613283dc96ba16db6f55cf431123949a0dd4d793": (46.02, 89.56),
    # Anxiety (Doechii)
    "1701d0ce9598456739060802dd680e9dd4cbe0b44deec633315e509217bfd49c": (93.06, 117.56),
    # APT (ROSE & Bruno Mars)
    "210213618c7a0b68e9fa22d3808807957faebfe0a59116577ea2550638465a3f": (45.39, 58.23),
    # As It Was (Harry Styles)
    "6d3b1295cde5f230066bd433cf4b13275ed74cc278975b10a186957cc0eb8c10": (58.8, 69.87),
    # Bangarang (SKRILLEX)
    "14e66918ffc2101e5e3b1770e0dc03d63cab2e6e35fda12979ae3716e8e49cc9": (27.42, 57.47),
    # Beautiful Things (Benson Boone)
    "7817281c27b5671d08460f00c8867db1cbfdd45326a08a5e647d6bd856faf84b": (85.7, 106.59),
    # Better (Khalid)
    "90f81c4506db38be718a243f87b3bda949e2edf0fba3f071d26bbb36554f3a99": (59.11, 78.71),
    # Better Off Alone (Alice Deejay)
    "7d5d7610aa5d0fb6ee5ecd4aeeb617f80d452af3b91009c3873d6f0129d3dfd5": (44.55, 58.61),
    # Billie Jean (Michael Jackson)
    "9d979f4b2ed8639b5ece3633e10e0ac2168c75f54851140811ece69e8d82bcaf": (87.79, 113.59),
    # BIRDS OF A FEATHER (Billie Eilish)
    "81e4dce757647473e06049ea13a702f51a46b9d4f4d5e8a70f77170b523a0a3d": (41.88, 60.16),
    # Blinding Lights (The Weeknd)
    "fcac6540e43f015070b2f531f12264bcb86b5d3b0320e6810ad47decaee9c122": (84.57, 106.72),
    # Breathing (Extended Mix)
    "3544ad08ac5732e8e1a914a3e7b8eae670bbfebc8358e97b35a966bd194a5782": (94.77, 126.01),
    # Calm Down (Rema, Selena Gomez)
    "9e7d9a4e31248aa2c6ffeb8f284cd52c0d74cd5c2b5409d6f5ce00c3188d04ee": (18.11, 35.94),
    # Cheerleader (Felix Jaehn Remix) (Ultra Records) (OMI)
    "5e8cf55583b8dc2929e0c790a284574bf549a802f2dae27c730751552f77541a": (49.41, 66.02),
    # Circles (Post Malone)
    "b8973a791e368b3c1c022266d1bf78b084384e6102cde4c6918fee999316bd04": (70.0, 88.19),
    # Cola (CamelPhat & Elderbrook)
    "db3a77daa0435dfae84ec14e244157534c2ee6af4c9265193ec4e88053868cd3": (126.75, 141.16),
    # Cruel Summer (Taylor Swift)
    "1a49818eea096ed2ad305bea2a2c2dc03289ab728692c1c90b06c1bb5cce3171": (29.62, 48.91),
    # DANCE MONKEY (TONES AND I)
    "841af1622092af9397b40c18b4421c89bd056fca7667019f6e2424ef609583d9": (64.53, 83.83),
    # Diamonds (Rihanna)
    "fb8c59ea98e8ae6ff1adbd84880e062c896a75e76d600464859f4eb44e801e31": (113.32, 134.07),
    # Die With A Smile (Lady Gaga, Bruno Mars)
    "e6e8eaf8849e7b342b8dc5c6e37cbfa95e012f285727d6ff06d9ce7464eb195b": (45.57, 63.8),
    # Don't Let Me Down (The Chainsmokers)
    "fb6ceb06165a3cba78a714aa28675c58007930d92f330025bfc61370701342cc": (41.96, 64.19),
    # Don't You Worry Child
    "6b31bbe2733a7cf9676b7b3215ef07f61fd096fd822d5c2b99147c6fa33c5d2d": (116.99, 131.1),
    # Dooriyan
    "c4b28366d0bd8a5dd0447d1dece9e204ae45f648ee066e0fc9bc04a068ba8b34": (45.14, 65.87),
    # Edge Of Desire (Radio Edit) (Jonas Blue, Malive)
    "0b90d142a07b9bdc583e9cc084ac270ab20854e0702fbf05a02808c99650d00c": (11.79, 39.17),
    # Espresso (Sabrina Carpenter)
    "21f23ca765e27e7222fad55c009ad9a2bcd3e1f4dbb32161863614ac9b9f558a": (22.63, 41.94),
    # F1
    "bcd556892b4d56847d584d8316cc21d68133c146efb9371b0e748f617faaa52f": (42.19, 77.08),
    # Father Ocean (Ben Böhmer Remix)
    "ac59f8c4af7e89e916dc825690ade5dbc2b9c6f221c5a7ef863eb9863f3826e1": (161.67, 201.71),
    # Feel So Close (Calvin Harris)
    "16611572f0e493e8a0a71ed8f42fd0d8fb4bf4ee839a16d1726840474a7a5aa4": (42.62, 72.08),
    # Fire Fire
    "61dc61b1af4860e4a359c905921d5dbe3021acc7569c0d27cca94624a291fa8f": (39.8, 55.09),
    # Flowers (Miley Cyrus)
    "59941074dfb7c27ccf14925ab1b442250fb940fdd6b4ebd03031461bdb7193ec": (34.71, 50.55),
    # Ghost (Justin Bieber)
    "dd40eda3f57a4b351f5b8f73a095d29136aaf167f8a7c1fcc7de3d02038e812f": (38.12, 63.57),
    # Gimme! Gimme! Gimme! (A Man After Midnight) (ABBA)
    "0b3fba00bfa4eb31eba969bf60266d30061df8405df8db32bb5a70466538b667": (68.93, 86.24),
    # God's Plan (Drake)
    "389e360294923a51e7b585a946b846755c675bf3af1cbac7d4e4db170a8bbc9e": (87.73, 93.28),
    # greedy (Tate McRae)
    "56ac90cf6899a46fe727bd5907032a80b16a93c900aa9701d98a2be5da709850": (26.71, 44.02),
    # Habits (Stay High) - Hippie Sabotage Remix (Tove Lo)
    "9e8a54168660d91228f04a325474acec21cd4163dc3f692e6594a4981c8e98ab": (80.05, 111.67),
    # Havana (Camila Cabello)
    "e09ca43dbbf6762301d49136be9a756dd45c38cac6d393248750fcead8495c50": (64.93, 83.44),
    # Heat Waves (Glass Animals)
    "c81935036ba970b29e10c329caef9c1a5dec66eebd76daad01b6999c628fc824": (30.29, 54.73),
    # Hey Brother
    "40350cd8721eb38d2043d8c0b8c6210539f3b4440931f7a1745459a8bb37ec1c": (34.85, 63.9),
    # Hold On, Were Going Home (Drake)
    "7d64ae25358564c39e44ce5d0db0373196a05b99b9d718ca06c2e8bf9e1d5571": (182.43, 240.51),
    # Houdini (Dua Lipa)
    "79481a6a4d7a6a2cf6ef04a202ab9bc9b74050277c3b84e47b92cc6a5fe6a393": (21.08, 38.18),
    # How Deep Is Your Love
    "4e24629370d87c887e2c0d711e740d4aa0c28206e6de6b499ee436cd5e72d97f": (62.84, 79.89),
    # HUMBLE (Kendrick Lamar)
    "459509efd2bfec67a3bec254516ebac97a1432f21ab61a4fa10a045c9ca08fc9": (55.71, 92.86),
    # I Adore You
    "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef": (34.05, 66.05),
    # I Want It That Way (Backstreet Boys)
    "ed97a4278e6381dcc1b8fd10c31d484082bf48bd8a76d2a9c5d6dcaf9e259804": (55.95, 73.76),
    # I Was Never There
    "cbd478ebcb72455d4f593e085c9f30afcda031466c3ea4a40380f36bd84c7df2": (68.59, 102.89),
    # In Da Club (50 Cent)
    "b70cf1c0d8c9575ae7b9c14e98a6deb1570f0b81e85c13813dcbc6f0756a00dd": (48.85, 71.04),
    # INDUSTRY BABY (Lil Nas X, Jack Harlow)
    "c1ce624e1b33e64a5bcb45ffc16936146f59312bdae4f69109abde877265d454": (35.82, 60.89),
    # Intentions ( (Short Version)) (Justin Bieber)
    "ac6e3e808c5f8d5f61340e5965f45749f119bc13d779b2377e9bb1428c7dcf1c": (13.3, 39.77),
    # Jimmy Cooks (Drake & 21 Savage)
    "bcc4adf14c6bdd7c8044f796c115163cb4202be51edcc03d4454d56135f82509": (25.8, 50.41),
    # Let Me Love You (DJ Snake)
    "707c5b95b05ca32a5cd5ba65ddcedc03d4d58c17f137eaefb586687de2523147": (47.77, 67.13),
    # Levels (Avicii)
    "0759b66b273f74c30d24e034340951afb8d5b783c2ffd0a1427a92a64cd93a4a": (84.42, 114.53),
    # Levitating Featuring DaBaby (Dua Lipa)
    "75bf3dadac1400a1c2d98b9229644f5ab4f2c534b2e030418343249b14203470": (24.34, 42.8),
    # Losing It
    "00260cff8a3f70f789aa597fd37f4cdcf7095e73ceb76ae42dd2e10bb9656769": (30.68, 45.82),
    # Martin
    "b4fe8d8601220990cb57b6581da5b248a482ba9c37e5bd49b59df174f466bd6e": (66.01, 97.99),
    # Memories (David Guetta)
    "1d370951c5b97789e2cd01b881992717a97d066cc12cfbc592e7eafd15f99b51": (15.34, 45.62),
    # Mo Bamba (Sheck Wes)
    "a49dbe8ea5f954b8a8cb50fcbbfe179f2a70e048cd7b5db33e9119882bd2ecae": (33.46, 59.63),
    # More Love (Rampa &ME Remix) (Moderat)
    "f66dc71806d5945c98bb600f37cfb18a5cdba670cb0d3fea01155e38b8149162": (64.12, 94.66),
    # Move
    "c226378f582106d68c0b73aef4bbe310c5df11c821940bc3add908ae17398522": (48.51, 56.47),
    # Move (Adam Port, Stryv)
    "cdc80f0a1121f5b91df996cac46e78ce49250341d7f1dce55a20bccfd419952b": (96.05, 104.07),
    # Not Like Us (Kendrick Lamar)
    "52938b2eb35ec8ce6b6d40fc001321acee44dc4ab00d1550646430ee02ebd3ba": (73.88, 91.49),
    # One Dance (Drake)
    "287d63cb95a9f71269843aaedd21f2fd72996c149d05736e59e03076fc9b6dab": (30.21, 47.54),
    # One Of The Girls (The Weeknd, JENNIE, Lily-Rose Depp)
    "3ccaa41588ebc4214f708585f6488cbc3d6934705478455f7d1813e7decc7bf0": (82.33, 115.13),
    # Paint The Town Red (Doja Cat)
    "8cb7a88269a58f8583f31db3b572f04bdc53f32d581098b15e51e81e6237474e": (63.65, 83.61),
    # positions (Ariana Grande)
    "0e66380c7b559b60fd30d6a019fc26b643fb20efe585fa9bc34f4682cc1c0ecf": (41.96, 54.98),
    # Pray For Me
    "4963f498eb92e041f1b1d6129ea6175de4c060f35a13a27428521b1d63b36e02": (52.76, 72.04),
    # Pretty Little Baby (Connie Francis)
    "28b0b5957ade7ea70d420d10d550ae6381bfc56d8d439eb0bfccfdf65ff88b61": (8.41, 31.4),
    # Psycho (Post Malone)
    "9d3108a9733e84b5e73e7d3acfa3f899527b529f6f0b8c98055fdb166c7fb97a": (28.82, 41.82),
    # Rasputin (Boney M)
    "206da5171c6f55096d123295be5499c9e4bffc464a515d45b4e85c2776c4ba71": (55.96, 87.2),
    # Reminder
    "8482ecdd16b9554a55480542b00d904a8a4d1b7e18deab3b3b3ece629e8388f1": (60.18, 83.71),
    # Ride It
    "3ad0da3cfafffe5277fdc2b2958337f5f3ea65968696c0a8ece79c86780ddc62": (51.45, 71.63),
    # Rolling in the Deep (Adele)
    "df950e91abfa00b4dd66f481d60a2ed1611ab9c8e4394cd4849ccfb2226a7fa4": (59.67, 77.81),
    # Satisfaction (Benny Benassi)
    "2666c3be4fae96e8087cdee8e7bb69d0129d563bbbe4d179a156715351bbe110": (34.02, 46.7),
    # Save Your Tears (The Weeknd)
    "589c36a80cb062000605235380172235ed95828c183737f17bf8f2d846977f98": (85.92, 98.26),
    # Say What (Keinemusik (Rampa, &ME, Adam Port))
    "36f47ca88fdb53448bd0660d34ac5fa18676b715865726a0f5971f6ffc820e83": (16.96, 48.13),
    # Sexy Chick (David Guetta)
    "98f9c702fdcc8765e2a46175103889cfd7e7c8438a3cc901ae388d1996831d67": (55.31, 84.78),
    # Shape of You (Ed Sheeran)
    "833785a3c8e4874b20da194500dc13210e98507c2ba4d34ac21e3bc687577607": (56.18, 84.04),
    # SICKO MODE (Travis Scott)
    "7d08a1c419cee2f58ad2139ec9734715bf915b8cbd1a3efc773f725cca1161f1": (64.8, 98.23),
    # Silence
    "9bf2835f9efdc58f4e3a83b95e8f1d6180ed10de0f49d183fa3690e15dec99e1": (67.62, 94.61),
    # Someone You Loved (Lewis Capaldi)
    "36dd448aabec28ab069eabc097a18a3e68497d75b5a5c43065f0ba0139ee706c": (25.35, 62.13),
    # Starboy
    "cc38bb39c856619a032b27881768a19c8f2c79013d07b26cd1269fd13157cf4f": (57.01, 77.76),
    # STAY (The Kid LAROI, Justin Bieber)
    "0fbe6967382ba5df934728427cf318f338f13acb1f9adacdbd5da0d646d1dc0e": (64.8, 87.35),
    # Summer (Calvin Harris)
    "fc64a4e1e60682187d05b1fccac85c00afc5d69408141a68ae9f231f81b7eece": (16.34, 46.27),
    # Summertime Sadness (Techno Remix)
    "92cd9266ea3748d840f0ccda1504f8939ad1744af32e8b0bb4a3febce7ccd29e": (35.04, 57.95),
    # Sunflower (Spider-Man_ Into the Spider-Verse) (Post Malone, Swae Lee)
    "9d1511cc049e72761eca125d3edc33a2fe0af1d579e920a918ba9dd5a6a90f0a": (71.58, 92.44),
    # São Paulo (The Weeknd)
    "b256d97cf565102a43055d247ec66f626b54e0d27907f54667a3dbb6488a7a16": (64.59, 79.42),
    # Talk (Khalid)
    "0deb0ff3593c918e21e10435a01a5227b8ff311195da782f72739f1c5be27d47": (24.57, 38.63),
    # Talk To You
    "ce355228955d0f53a21f97b783b190a78ff28a141fc20aea1505c83fd4f17e29": (73.09, 97.15),
    # ten
    "d0e36adb85dd60c14e12baa016127c299b9d9ca5958a719a5d8ae86fd6f6cd0a": (15.76, 30.72),
    # This Is What You Came For (Calvin Harris, Rihanna)
    "ee5371cc0df6f42130763d2086deabe319eeb4d0392cceb5eb417bb46e937060": (31.91, 62.9),
    # Titanium (David Guetta)
    "fa79359d8ad718f8cbad693b42749b21a71eeba9e57e91c31295ac5062fbf0f6": (46.82, 76.39),
    # Tremor (Dimitri Vegas, Martin Garrix, Like Mike)
    "e1dd7baadeae5a5955c30230ed544a55e3222f7dae69b3654a227a57069b9d00": (53.88, 68.82),
    # Umbrella (Orange Version) (Rihanna)
    "08bbff44645a98192a3ede0b802eda1ac9a796cb350e029b987c98cc79c12151": (56.32, 84.31),
    # Uptown Funk (Mark Ronson)
    "acce9a2d7a520b662d403c2cf9167c41c0930fa7fa75daa50899ade058a4fea2": (66.5, 85.27),
    # Water (Tyla)
    "5a4f7cbb1fe02a69a85c0a721c78f497121d1087e91868d2c44be22b06d8cc41": (90.17, 106.54),
    # Watermelon Sugar (Harry Styles)
    "09c1cb6bac71d84ae91ec0f2eda911ca917989d3673098052b07190dabc2f4cf": (51.75, 61.75),
    # We Found Love (Rihanna)
    "64e72fa137a463944159a1dcc798544ec5a48ba2c442164d16d0cf06eb2b4e64": (119.35, 135.01),
    # Where Are Ü Now with Justin Bieber (Skrillex and Diplo)
    "85f6e56153c57e4cfa8dcc38c7f5c160d5947fcf3459b17653ba3226ad55e3d5": (69.65, 96.71),
    # Woman (Doja Cat)
    "5002e158a1b9d042d9b41d336e6ec6cbc53acf5f7f2c288a239e0dea20227b31": (32.71, 51.74),
    # Yamore (MoBlack, Salif Keita, Benja(NL))
    "d1b04d989f53ad9165c17bbd5a928ba87aaf57c5c21cfcc3ada58c03aaf48f97": (7.57, 39.44),
    # Young Dumb & Broke (Khalid)
    "ac45ac43af547365d20228de1f9121728cf967a0a7b07d2a1927929cfbc21eb2": (54.26, 81.88),
}

# song content id -> [main drop time(s), secs, native timeline]. A listed beat uses these INSTEAD of
# automatic energy detection (which measured ~36% precision on the songs that were checked).
GEN_MAIN_DROPS: dict[str, list[float]] = {
    # abcdefu (GAYLE)
    "f90c50e5f3e5dedc60fd01225a5257bd870a28452c8f0f9beb0ebfe3ed1680a5": [56.26, 69.09],
    # All The Stars (Kendrick Lamar, SZA)
    "0c3ba845896f89d854b28dc8c094697b3c6933b8a7cd0a46840e38299f4a9542": [40.39],
    # Anchor Point (Ahmed Spins)
    "2c17fc64b6928f0499a306402b676bc62e3118588e42494c8ec7063a7a948267": [31.87, 85.25],
    # Animals (Martin Garrix)
    "6bbf744033c9d61a7c15fa2a613283dc96ba16db6f55cf431123949a0dd4d793": [46.12, 90.42],
    # Anxiety (Doechii)
    "1701d0ce9598456739060802dd680e9dd4cbe0b44deec633315e509217bfd49c": [93.08],
    # APT (ROSE & Bruno Mars)
    "210213618c7a0b68e9fa22d3808807957faebfe0a59116577ea2550638465a3f": [6.9, 45.41],
    # As It Was (Harry Styles)
    "6d3b1295cde5f230066bd433cf4b13275ed74cc278975b10a186957cc0eb8c10": [46.29, 58.82],
    # Bad Guy
    "e276a2ef08ece15e1e8bd314404757301c787f0374ce4f3b79d8d15d33eb5bd3": [56.83, 74.51],
    # Bangarang (SKRILLEX)
    "14e66918ffc2101e5e3b1770e0dc03d63cab2e6e35fda12979ae3716e8e49cc9": [27.43],
    # Beautiful Things (Benson Boone)
    "7817281c27b5671d08460f00c8867db1cbfdd45326a08a5e647d6bd856faf84b": [85.68],
    # Better (Khalid)
    "90f81c4506db38be718a243f87b3bda949e2edf0fba3f071d26bbb36554f3a99": [29.98, 59.1],
    # Better Off Alone (Alice Deejay)
    "7d5d7610aa5d0fb6ee5ecd4aeeb617f80d452af3b91009c3873d6f0129d3dfd5": [30.34, 44.59],
    # Billie Jean (Michael Jackson)
    "9d979f4b2ed8639b5ece3633e10e0ac2168c75f54851140811ece69e8d82bcaf": [87.76],
    # BIRDS OF A FEATHER (Billie Eilish)
    "81e4dce757647473e06049ea13a702f51a46b9d4f4d5e8a70f77170b523a0a3d": [41.9],
    # Blinding Lights (The Weeknd)
    "fcac6540e43f015070b2f531f12264bcb86b5d3b0320e6810ad47decaee9c122": [62.15, 84.58],
    # Breathing (Extended Mix)
    "3544ad08ac5732e8e1a914a3e7b8eae670bbfebc8358e97b35a966bd194a5782": [63.21, 94.73],
    # Calm Down (Rema, Selena Gomez)
    "9e7d9a4e31248aa2c6ffeb8f284cd52c0d74cd5c2b5409d6f5ce00c3188d04ee": [18.13, 36.21],
    # Cheerleader (Felix Jaehn Remix) (Ultra Records) (OMI)
    "5e8cf55583b8dc2929e0c790a284574bf549a802f2dae27c730751552f77541a": [49.41],
    # Circles (Post Malone)
    "b8973a791e368b3c1c022266d1bf78b084384e6102cde4c6918fee999316bd04": [38.51, 70.36],
    # Cola (CamelPhat & Elderbrook)
    "db3a77daa0435dfae84ec14e244157534c2ee6af4c9265193ec4e88053868cd3": [126.74, 141.16],
    # Cruel Summer (Taylor Swift)
    "1a49818eea096ed2ad305bea2a2c2dc03289ab728692c1c90b06c1bb5cce3171": [29.64],
    # DANCE MONKEY (TONES AND I)
    "841af1622092af9397b40c18b4421c89bd056fca7667019f6e2424ef609583d9": [64.57],
    # Der Lagi Lekin (ZNMD)
    "bbab7b9f875f071f8e3b53aa73e64c02b3f39730d0a1feec48af6b54de501430": [17.66, 65.24],
    # Diamonds (Rihanna)
    "fb8c59ea98e8ae6ff1adbd84880e062c896a75e76d600464859f4eb44e801e31": [91.64, 113.28],
    # Die With A Smile (Lady Gaga, Bruno Mars)
    "e6e8eaf8849e7b342b8dc5c6e37cbfa95e012f285727d6ff06d9ce7464eb195b": [45.56],
    # Don't Let Me Down (The Chainsmokers)
    "fb6ceb06165a3cba78a714aa28675c58007930d92f330025bfc61370701342cc": [41.96, 65.36],
    # Don't Start Now (Dua Lipa)
    "c0c6ab91a06e24367e84874da81d4abc285779f50e8f1aeacf70a655cabceb0b": [36.5, 51.73],
    # Don't You Worry Child
    "6b31bbe2733a7cf9676b7b3215ef07f61fd096fd822d5c2b99147c6fa33c5d2d": [116.98, 160.01],
    # Dooriyan
    "c4b28366d0bd8a5dd0447d1dece9e204ae45f648ee066e0fc9bc04a068ba8b34": [46.18],
    # Edge Of Desire (Radio Edit) (Jonas Blue, Malive)
    "0b90d142a07b9bdc583e9cc084ac270ab20854e0702fbf05a02808c99650d00c": [11.82],
    # Espresso (Sabrina Carpenter)
    "21f23ca765e27e7222fad55c009ad9a2bcd3e1f4dbb32161863614ac9b9f558a": [22.6],
    # F1
    "bcd556892b4d56847d584d8316cc21d68133c146efb9371b0e748f617faaa52f": [33.84, 42.22],
    # Father Ocean (Ben Böhmer Remix)
    "ac59f8c4af7e89e916dc825690ade5dbc2b9c6f221c5a7ef863eb9863f3826e1": [236.18],
    # Feel So Close (Calvin Harris)
    "16611572f0e493e8a0a71ed8f42fd0d8fb4bf4ee839a16d1726840474a7a5aa4": [72.07, 86.92],
    # Fire Fire
    "61dc61b1af4860e4a359c905921d5dbe3021acc7569c0d27cca94624a291fa8f": [39.79],
    # Flowers (Miley Cyrus)
    "59941074dfb7c27ccf14925ab1b442250fb940fdd6b4ebd03031461bdb7193ec": [34.69],
    # Ghost (Justin Bieber)
    "dd40eda3f57a4b351f5b8f73a095d29136aaf167f8a7c1fcc7de3d02038e812f": [37.85, 63.56],
    # Gimme! Gimme! Gimme! (A Man After Midnight) (ABBA)
    "0b3fba00bfa4eb31eba969bf60266d30061df8405df8db32bb5a70466538b667": [18.41, 68.93],
    # God's Plan (Drake)
    "389e360294923a51e7b585a946b846755c675bf3af1cbac7d4e4db170a8bbc9e": [40.28, 93.12],
    # greedy (Tate McRae)
    "56ac90cf6899a46fe727bd5907032a80b16a93c900aa9701d98a2be5da709850": [26.71],
    # Habits (Stay High) - Hippie Sabotage Remix (Tove Lo)
    "9e8a54168660d91228f04a325474acec21cd4163dc3f692e6594a4981c8e98ab": [16.63, 80.08],
    # Havana (Camila Cabello)
    "e09ca43dbbf6762301d49136be9a756dd45c38cac6d393248750fcead8495c50": [47.04, 64.92],
    # Heat Waves (Glass Animals)
    "c81935036ba970b29e10c329caef9c1a5dec66eebd76daad01b6999c628fc824": [30.32],
    # Hold On, Were Going Home (Drake)
    "7d64ae25358564c39e44ce5d0db0373196a05b99b9d718ca06c2e8bf9e1d5571": [182.39, 220.77],
    # Houdini (Dua Lipa)
    "79481a6a4d7a6a2cf6ef04a202ab9bc9b74050277c3b84e47b92cc6a5fe6a393": [21.11],
    # How Deep Is Your Love
    "4e24629370d87c887e2c0d711e740d4aa0c28206e6de6b499ee436cd5e72d97f": [62.82, 94.31],
    # Hum Pyaar Karne Wale
    "262ee1c3ac150081b643637b63c209ac29244c5ca764d8c2317b7e0106b016e3": [75.55],
    # HUMBLE (Kendrick Lamar)
    "459509efd2bfec67a3bec254516ebac97a1432f21ab61a4fa10a045c9ca08fc9": [55.73],
    # I Adore You
    "b8696c4dec8a4d50c2ee493360a868d46ffcc915a43b0fdfdbe30241d9962bef": [18.04, 34.05],
    # I Want It That Way (Backstreet Boys)
    "ed97a4278e6381dcc1b8fd10c31d484082bf48bd8a76d2a9c5d6dcaf9e259804": [37.3, 55.93],
    # I Was Never There
    "cbd478ebcb72455d4f593e085c9f30afcda031466c3ea4a40380f36bd84c7df2": [102.9],
    # In Da Club (50 Cent)
    "b70cf1c0d8c9575ae7b9c14e98a6deb1570f0b81e85c13813dcbc6f0756a00dd": [48.86],
    # In My Mind (Dynoro & Gigi DAgostino)
    "c9cff695d4c3ba16afe27a5e8778edd1d6fd76572d0f69ac75cbec276033743a": [48.92],
    # INDUSTRY BABY (Lil Nas X, Jack Harlow)
    "c1ce624e1b33e64a5bcb45ffc16936146f59312bdae4f69109abde877265d454": [35.82],
    # Intentions ( (Short Version)) (Justin Bieber)
    "ac6e3e808c5f8d5f61340e5965f45749f119bc13d779b2377e9bb1428c7dcf1c": [13.32],
    # Jimmy Cooks (Drake & 21 Savage)
    "bcc4adf14c6bdd7c8044f796c115163cb4202be51edcc03d4454d56135f82509": [25.83],
    # Jugni Ji
    "cb3e96493087255ef535db47d04388f51d2de27e20c6cb13dd626092778aae43": [10.21],
    # Khuda Jaane
    "457d170c17dea1fc8644c479788efff6c1bfc5b5c4b3fa5897e43a6c0e5ce751": [60.15],
    # Let Me Love You (DJ Snake)
    "707c5b95b05ca32a5cd5ba65ddcedc03d4d58c17f137eaefb586687de2523147": [28.7, 67.22],
    # Levels (Avicii)
    "0759b66b273f74c30d24e034340951afb8d5b783c2ffd0a1427a92a64cd93a4a": [7.55, 53.57],
    # Levitating Featuring DaBaby (Dua Lipa)
    "75bf3dadac1400a1c2d98b9229644f5ab4f2c534b2e030418343249b14203470": [24.41, 33.74],
    # Location
    "74d3aac12e9256b7d9a8358a92e3632a5a2384352b4b3f9db78600029338b915": [14.06],
    # Losing It
    "00260cff8a3f70f789aa597fd37f4cdcf7095e73ceb76ae42dd2e10bb9656769": [30.7],
    # Martin
    "b4fe8d8601220990cb57b6581da5b248a482ba9c37e5bd49b59df174f466bd6e": [66.0],
    # Memories (David Guetta)
    "1d370951c5b97789e2cd01b881992717a97d066cc12cfbc592e7eafd15f99b51": [15.36],
    # Mo Bamba (Sheck Wes)
    "a49dbe8ea5f954b8a8cb50fcbbfe179f2a70e048cd7b5db33e9119882bd2ecae": [33.43],
    # More Love (Rampa &ME Remix) (Moderat)
    "f66dc71806d5945c98bb600f37cfb18a5cdba670cb0d3fea01155e38b8149162": [64.13, 94.67],
    # Move
    "c226378f582106d68c0b73aef4bbe310c5df11c821940bc3add908ae17398522": [48.53, 56.51],
    # Move (Adam Port, Stryv)
    "cdc80f0a1121f5b91df996cac46e78ce49250341d7f1dce55a20bccfd419952b": [64.55, 104.17],
    # Nadan Parinde
    "84e4ea36d2f3cb34f7e1beb4ce1bace077083994e700b7cc73347e2f5b5438f3": [70.66, 124.68],
    # Not Like Us (Kendrick Lamar)
    "52938b2eb35ec8ce6b6d40fc001321acee44dc4ab00d1550646430ee02ebd3ba": [7.15, 74.23],
    # Old Town Road
    "d20b34a7c5953dae9915496740a21656928e89bac8d03994068ce50573df1ded": [28.55],
    # One Dance (Drake)
    "287d63cb95a9f71269843aaedd21f2fd72996c149d05736e59e03076fc9b6dab": [7.57, 53.3],
    # One Of The Girls (The Weeknd, JENNIE, Lily-Rose Depp)
    "3ccaa41588ebc4214f708585f6488cbc3d6934705478455f7d1813e7decc7bf0": [27.54, 82.32],
    # Paint The Town Red (Doja Cat)
    "8cb7a88269a58f8583f31db3b572f04bdc53f32d581098b15e51e81e6237474e": [63.66],
    # Panda
    "f4cdd8c9f40266c534aecc3ce1ba82bb7dfb5672a2cbcf0ff2c28d712ccbdf86": [40.29],
    # positions (Ariana Grande)
    "0e66380c7b559b60fd30d6a019fc26b643fb20efe585fa9bc34f4682cc1c0ecf": [28.48, 42.54],
    # Pray For Me
    "4963f498eb92e041f1b1d6129ea6175de4c060f35a13a27428521b1d63b36e02": [33.54, 52.55],
    # Pretty Little Baby (Connie Francis)
    "28b0b5957ade7ea70d420d10d550ae6381bfc56d8d439eb0bfccfdf65ff88b61": [8.43],
    # Psycho (Post Malone)
    "9d3108a9733e84b5e73e7d3acfa3f899527b529f6f0b8c98055fdb166c7fb97a": [28.81],
    # Rapture (Black Coffee)
    "7f0b66c94d2be61f18a64485dba0a33b5f4387ccce2ff1b5d23aa7da469076eb": [64.26],
    # Rasputin (Boney M)
    "206da5171c6f55096d123295be5499c9e4bffc464a515d45b4e85c2776c4ba71": [48.39, 103.81],
    # redrum
    "fe7f43df1b36b400c93a96c69f33a8ba275ece6f72ed8e2ac95f242869232ab7": [44.95, 56.72],
    # Reminder
    "8482ecdd16b9554a55480542b00d904a8a4d1b7e18deab3b3b3ece629e8388f1": [36.14, 60.17],
    # Ride It
    "3ad0da3cfafffe5277fdc2b2958337f5f3ea65968696c0a8ece79c86780ddc62": [51.46, 145.93],
    # Rolling in the Deep (Adele)
    "df950e91abfa00b4dd66f481d60a2ed1611ab9c8e4394cd4849ccfb2226a7fa4": [59.66],
    # Roses (The Chainsmokers)
    "a5ac2257e830a9e854591ffaf5acd6fbc2bcf053225140fcb14dd1b1ae896106": [68.14, 87.46],
    # Satisfaction (Benny Benassi)
    "2666c3be4fae96e8087cdee8e7bb69d0129d563bbbe4d179a156715351bbe110": [33.97],
    # Save Your Tears (The Weeknd)
    "589c36a80cb062000605235380172235ed95828c183737f17bf8f2d846977f98": [58.98, 85.94],
    # Say What (Keinemusik (Rampa, &ME, Adam Port))
    "36f47ca88fdb53448bd0660d34ac5fa18676b715865726a0f5971f6ffc820e83": [16.98],
    # Scary Monsters And Nice Sprites (Skrillex)
    "084c6bfaa208e61ec360adb73ee48475292255998495d16d70ee0797242641dd": [41.53],
    # Sexy Chick (David Guetta)
    "98f9c702fdcc8765e2a46175103889cfd7e7c8438a3cc901ae388d1996831d67": [55.32, 84.77],
    # Shape of You (Ed Sheeran)
    "833785a3c8e4874b20da194500dc13210e98507c2ba4d34ac21e3bc687577607": [36.16, 56.2],
    # SICKO MODE (Travis Scott)
    "7d08a1c419cee2f58ad2139ec9734715bf915b8cbd1a3efc773f725cca1161f1": [64.82],
    # Sirens (Extended Version)
    "462e546d2e60e9ecba89f6f3a47758cf3c4138d0f2cedc9d1f9a802eaec0cd8f": [71.57, 103.59],
    # Someone You Loved (Lewis Capaldi)
    "36dd448aabec28ab069eabc097a18a3e68497d75b5a5c43065f0ba0139ee706c": [25.39, 43.64],
    # Starboy
    "cc38bb39c856619a032b27881768a19c8f2c79013d07b26cd1269fd13157cf4f": [36.53, 57.04],
    # STAY (The Kid LAROI, Justin Bieber)
    "0fbe6967382ba5df934728427cf318f338f13acb1f9adacdbd5da0d646d1dc0e": [50.69, 64.82],
    # Summer (Calvin Harris)
    "fc64a4e1e60682187d05b1fccac85c00afc5d69408141a68ae9f231f81b7eece": [16.23, 61.33],
    # Summertime Sadness (Techno Remix)
    "92cd9266ea3748d840f0ccda1504f8939ad1744af32e8b0bb4a3febce7ccd29e": [35.06],
    # Sunflower (Spider-Man_ Into the Spider-Verse) (Post Malone, Swae Lee)
    "9d1511cc049e72761eca125d3edc33a2fe0af1d579e920a918ba9dd5a6a90f0a": [28.39, 71.57],
    # São Paulo (The Weeknd)
    "b256d97cf565102a43055d247ec66f626b54e0d27907f54667a3dbb6488a7a16": [64.57, 79.61],
    # Talk (Khalid)
    "0deb0ff3593c918e21e10435a01a5227b8ff311195da782f72739f1c5be27d47": [24.57],
    # Talk To You
    "ce355228955d0f53a21f97b783b190a78ff28a141fc20aea1505c83fd4f17e29": [73.09],
    # ten
    "d0e36adb85dd60c14e12baa016127c299b9d9ca5958a719a5d8ae86fd6f6cd0a": [15.75],
    # Tere Bin
    "84ff0d8b12455dc66e971874b64ae3b816d622f7fc947cfba12cca77fe6eea88": [60.09],
    # Tere Bina
    "6ad6903592cd668502c5f4546618aec807c6eadb974fa6437fef7180fbffddc2": [27.38],
    # This Is What You Came For (Calvin Harris, Rihanna)
    "ee5371cc0df6f42130763d2086deabe319eeb4d0392cceb5eb417bb46e937060": [31.86, 63.03],
    # Titanium (David Guetta)
    "fa79359d8ad718f8cbad693b42749b21a71eeba9e57e91c31295ac5062fbf0f6": [46.84, 76.39],
    # Tremor (Dimitri Vegas, Martin Garrix, Like Mike)
    "e1dd7baadeae5a5955c30230ed544a55e3222f7dae69b3654a227a57069b9d00": [23.58, 54.23],
    # Tujhe Bhula Diya (Anjaana Anjaani)
    "fedc95c90aff7c957f398f302a6a3ed4c7dbf48d7a6667c8294e0b4030355e20": [44.26, 58.84],
    # Turn Down for What (DJ Snake, Lil Jon)
    "02cb80a396f42d5e63c93f493d32555c104514e87c940cce4424f5585491400f": [20.77],
    # Uff Teri Ada
    "5c3ce60868f97c5657d32cc14a028b349fab07bfdf984c40f401790fd1c82375": [82.12],
    # Umbrella (Orange Version) (Rihanna)
    "08bbff44645a98192a3ede0b802eda1ac9a796cb350e029b987c98cc79c12151": [56.29],
    # Uptown Funk (Mark Ronson)
    "acce9a2d7a520b662d403c2cf9167c41c0930fa7fa75daa50899ade058a4fea2": [66.54],
    # Waiting For Love
    "5a06f0302cc99ad8491fe3b6fd0748b3365a958b74e10bd226350497c6923d49": [75.39, 105.44],
    # Water (Tyla)
    "5a4f7cbb1fe02a69a85c0a721c78f497121d1087e91868d2c44be22b06d8cc41": [90.16],
    # Watermelon Sugar (Harry Styles)
    "09c1cb6bac71d84ae91ec0f2eda911ca917989d3673098052b07190dabc2f4cf": [51.78, 61.76],
    # We Found Love (Rihanna)
    "64e72fa137a463944159a1dcc798544ec5a48ba2c442164d16d0cf06eb2b4e64": [64.06, 119.31],
    # Where Are Ü Now with Justin Bieber (Skrillex and Diplo)
    "85f6e56153c57e4cfa8dcc38c7f5c160d5947fcf3459b17653ba3226ad55e3d5": [69.64, 96.96],
    # With You (AP Dhillon)
    "ae132f3a444f5121d75097a44110a0323365e6dc4a8d0736a924c00b2ac210c1": [18.97],
    # Woman (Doja Cat)
    "5002e158a1b9d042d9b41d336e6ec6cbc53acf5f7f2c288a239e0dea20227b31": [33.13],
    # Yamore (MoBlack, Salif Keita, Benja(NL))
    "d1b04d989f53ad9165c17bbd5a928ba87aaf57c5c21cfcc3ada58c03aaf48f97": [7.57],
    # Young Dumb & Broke (Khalid)
    "ac45ac43af547365d20228de1f9121728cf967a0a7b07d2a1927929cfbc21eb2": [27.62, 54.23],
}

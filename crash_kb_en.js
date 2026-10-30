(function (g) {
  const R = {
    'model-pool': {
      title: 'Model storage (ModelInfo) is full or a model ID is invalid',
      c: [
        'The game was registering a new model from an IDE line. The storage for that model type is already full, so the allocation returned null and the game wrote to null plus a small offset. This matches the very small fault address.',
        'Common causes: too many mods adding objects, vehicles, peds or weapons (map packs, mod loaders), duplicate model IDs, or IDs outside the 0-19999 range.',
        'Default game limits per type: atomic 14000, damage atomic 70, time 169, clump 5, ped 130, vehicle 110, weapon 37.'
      ],
      f: [
        'Reduce or remove mods that add models. Test by moving mods such as ZyZ ModLoader, XkiLoader and map mods out one at a time.',
        'Make sure a limit adjuster suitable for the 64-bit game is active and its model/IDE limit is raised. Do not install several limit adjusters that change the same limit.',
        'Check mod IDE files: no duplicate IDs, every ID unique and below 20000, and the column count of each line matches its type (objs, tobj, cars, ped, weap).',
        'If the crash started after adding one mod, remove that mod and try again.'
      ]
    },
    'ide-load': {
      title: 'Crash while reading IDE/DAT files (level loading at startup)',
      c: [
        'The crash happens while the game loads the object list from gta.dat and the IDE files, so the trigger is almost always mod data rather than anything done in gameplay.',
        'An IDE line has the wrong format or column count, a model or TXD name is duplicated, or an IDE/DAT file is corrupted.'
      ],
      f: [
        'Check the mod you added most recently: its IDE files, gta.dat/default.dat and the mod loader folder.',
        'Save data files as plain text (UTF-8 without BOM) with consistent line endings.',
        'Search for the model name shown in the evidence section across all .ide files to find the mod responsible.',
        'Move object-adding mods out one by one (binary search) until the game starts.'
      ]
    },
    'ipl-load': {
      title: 'Crash while reading IPL / object instances',
      c: [
        'An IPL uses a model ID that does not exist in any IDE, or the number of instances exceeds a pool (Building, Dummy, Object, PtrNode).',
        'A streamed (binary) IPL file is corrupted or does not match the IMG contents.'
      ],
      f: [
        'Make sure every ID in the IPL is defined in an IDE. Check the map mod you installed last.',
        'Raise the relevant pool with a limit adjuster.',
        'Reinstall the map mod IPL/IMG files from the original source.'
      ]
    },
    'streaming': {
      title: 'Model streaming / IMG archive problem',
      c: [
        'A requested model is missing, an IMG entry has the wrong size, or the IMG archive is corrupted or truncated by an incomplete copy.',
        'Streaming memory ran out because of too many HD textures or models.'
      ],
      f: [
        'Check the size and integrity of gta3.img and mod IMG files, then copy them again.',
        'Raise the streaming memory limit moderately. Do not overdo it on phones with little RAM.',
        'Remove model/DFF files you added recently.'
      ]
    },
    'txd': {
      title: 'TXD / texture problem',
      c: [
        'A TXD is corrupted, the texture format is not supported by the GPU, or the resolution is so large that raster allocation fails.',
        'A parent TXD is missing or texture names clash between TXDs.'
      ],
      f: [
        'Use a texture format that matches the Android game package (DXT/PVR/ETC) and avoid very large resolutions.',
        'Compress or downscale mod textures. Check the texture names used by the DFF.',
        'Restore the original TXD to find out which TXD is responsible.'
      ]
    },
    'dff': {
      title: 'Corrupted DFF / model geometry',
      c: [
        'A DFF is corrupted or uses the wrong RenderWare version, has empty geometry, or lacks required frames and dummies (chassis, wheel_*_dummy).',
        'Skin or bones do not match the ped skeleton, or there are too many materials.'
      ],
      f: [
        'Re-export the DFF with the GTA SA RenderWare version and standard frame names.',
        'Make sure vehicles have the required frames.',
        'Replace the modded model with the original to confirm which DFF is responsible.'
      ]
    },
    'vehicle': {
      title: 'Vehicle problem (handling, model or spawn)',
      c: [
        'handling.cfg, vehicles.ide, carcols or carmods is incomplete for a modded vehicle, or model dummies and components are missing.',
        'Mods that change vehicles (tuning, deform, sirens, ModelExtras) use data that is not available on certain vehicles.'
      ],
      f: [
        'Make sure every modded vehicle has a correct handling ID, handling.cfg entry, carcols and vehicles.ide entries.',
        'Temporarily disable vehicle mods (BeamNG Damage, Tuning, VSL, ModelExtras), then enable them one by one.',
        'Test the same vehicle on its own to confirm its model.'
      ]
    },
    'ped-anim': {
      title: 'Ped / animation problem',
      c: [
        'An animation (IFP) or animation block is not loaded or does not match the ped skeleton. ped.ifp may be corrupted, or an animation/combat mod is incompatible.',
        'A modded ped lacks pedstats or pedgrp entries, or its model had not finished streaming when it was used.'
      ],
      f: [
        'Restore the original ped.ifp and IFP files, then test.',
        'Disable animation and combat mods (FightBlock, PCScreenGesture, Rolling, Advanced Aiming).',
        'Make sure modded peds have correct IDE, pedstats and pedgrp entries.'
      ]
    },
    'weapon': {
      title: 'Weapon problem',
      c: [
        'weapon.dat has too few or too many columns, or a weapon ID does not exist. The weapon model has not been loaded.',
        'Weapon, tracer or aim mods that hook the shooting code are incompatible with modded weapons.'
      ],
      f: [
        'Check weapon.dat and the IDE entries of modded weapons.',
        'Disable BulletTracers, Advanced Aiming, GrenadeAim, Weapon Details and Weapon On Player one at a time.',
        'Restore the original weapon.dat to test.'
      ]
    },
    'fx': {
      title: 'Particle effects (FX) problem',
      c: [
        'An effects file (.fxp) is corrupted or the FX limits are exceeded, especially with many effect mods active (fire, smoke, trails, contrails, oil leaks).',
        'An effect name could not be found.'
      ],
      f: [
        'Raise the limits with FxLimitAdjuster and reduce effect mods.',
        'Disable effect mods (ClassicFX, Plane Contrail, OilLeak) to test.',
        'Restore the original effects.fxp.'
      ]
    },
    'audio': {
      title: 'Audio problem',
      c: [
        'A mod audio file (mp3, wav, ogg or SFX bank) is corrupted or in an unsupported format, or the audio and BASS threads hit a race condition.',
        'An audio or radio mod is not compatible with the BASS Sound Library version.'
      ],
      f: [
        'Remove audio and radio mods, then test.',
        'Update the BASS Sound Library and the mods that depend on it.',
        'Convert audio to a standard format.'
      ]
    },
    'gpu': {
      title: 'Crash inside the GPU / graphics driver',
      c: [
        'The crash happened inside the GPU driver, usually because of an invalid texture, shader or framebuffer, GPU memory exhaustion, or a driver bug with post-processing effects.'
      ],
      f: [
        'Lower resolution and texture quality, and turn off shader and post-processing effects (ClassicFX, Project 2DFX, visual mods).',
        'Update the device system software and close other apps.',
        'Test on another device if possible.'
      ]
    },
    'libc': {
      title: 'Crash in a C library function (memory/string)',
      c: [
        'A string or memory copy/read function received an invalid pointer from its caller: a null pointer, a string without a terminator, or a buffer that was already freed.'
      ],
      f: [
        'Look at the caller in the call chain shown in the evidence section. That is the code that is actually at fault.',
        'If the caller is a mod, update or remove that mod.',
        'Make sure the data files being read (txt, dat, ide, cfg) are not empty or corrupted.'
      ]
    },
    'abort': {
      title: 'The game terminated itself (abort / exception)',
      c: [
        'SIGABRT means the program called abort. It is usually an unhandled C++ exception (for example bad_alloc from running out of memory), an assertion, or detected heap corruption such as a double free or buffer overflow.'
      ],
      f: [
        'Close other apps and reduce mods that use a lot of memory (HD textures, many vehicles).',
        'Remove recently installed mods and test again.',
        'If the crash location keeps changing, suspect heap corruption by a mod that hooks memory.'
      ]
    },
    'sigbus': {
      title: 'Misaligned memory access or truncated mapped file (SIGBUS)',
      c: [
        'SIGBUS occurs on misaligned access or when a memory-mapped file is truncated or missing, for example an OBB or IMG changed while the game runs, or storage was disconnected.'
      ],
      f: [
        'Copy the OBB and game data again, and make sure storage has enough free space and is stable.',
        'Do not move or modify game files while the game is running.'
      ]
    },
    'sigfpe': {
      title: 'Division by zero (SIGFPE)',
      c: [
        'A calculation divided by zero, usually because of a 0 value in data (mass or size in handling.cfg, effect parameters or mod configuration).'
      ],
      f: [
        'Check handling.cfg and any mod configuration you changed recently.',
        'Restore the values to defaults and test.'
      ]
    },
    'sigill': {
      title: 'Illegal instruction / faulty mod patch (SIGILL or SIGTRAP)',
      c: [
        'The CPU executed invalid data or an invalid instruction. Common causes: a mod patch or hook writing to the wrong address because the game version does not match, or a 32-bit mod used with the 64-bit game.'
      ],
      f: [
        'Make sure all mods have the same architecture as the game (arm64) and support your game version.',
        'Update the mods, then remove them one by one to find the culprit.'
      ]
    },
    'init': {
      title: 'Crash during game initialization (before the menu)',
      c: [
        'The crash happens before the game reaches the menu, so the cause is usually a mod data file or a mod conflict at load time, not gameplay.'
      ],
      f: [
        'Remove all mods, then add several back at a time (binary search) until the crash returns.',
        'Once you find the culprit group, narrow it down to a single mod.'
      ]
    },
    'save': {
      title: 'Save game problem',
      c: [
        'The save contains model or vehicle data from a mod that is no longer installed, or the save file is corrupted.'
      ],
      f: [
        'Reinstall the mods that were active when the save was made.',
        'Try another save slot or a backup, and do not overwrite the corrupted save file.'
      ]
    },
    'gxt': {
      title: 'Text (GXT) problem',
      c: [
        'The GXT file is corrupted, a text key was not found, or a text mod does not match the game language.'
      ],
      f: [
        'Restore the original GXT file and reinstall a text mod that matches your game version.'
      ]
    },
    'script': {
      title: 'Script problem (main.scm / CLEO)',
      c: [
        'A script uses a command or model ID that does not exist, or main.scm does not match the installed mods.'
      ],
      f: [
        'Disable the script mod you installed most recently.',
        'Make sure script-based mods support the game version you use.'
      ]
    },
    'ui': {
      title: 'HUD / menu / radar / on-screen controls problem',
      c: [
        'HUD textures or data were not found, or menu, radar and on-screen control mods clash with the default layout.'
      ],
      f: [
        'Disable interface mods (PC Menu, GPS, Wanted Radar, HUD mods), then test.',
        'Restore the original HUD files and textures.'
      ]
    },
    'collision': {
      title: 'Collision problem',
      c: [
        'A COL file is corrupted or a model has no valid collision, or an error occurred in a physics check.'
      ],
      f: [
        'Make sure new models have valid COL data. Reinstall the mod COL files.',
        'Disable physics and damage mods (BeamNG Damage) to test.'
      ]
    },
    'world': {
      title: 'World / rendering problem (entities, shadows, lights, weather)',
      c: [
        'An entity or model is incomplete when rendered, or an error occurred in shadows, coronas, lights, water or timecyc.',
        'LOD, 2DFX, siren and light mods can exceed internal limits.'
      ],
      f: [
        'Disable Project 2DFX, VSL and other light or visual mods one at a time.',
        'Make sure timecyc.dat, water.dat and IPL files were not changed into a wrong format.'
      ]
    },
    'recursion': {
      title: 'Endless recursion / stack overflow',
      c: [
        'The same function repeats very many times in the call chain. This indicates endless recursion or two hooks calling each other.'
      ],
      f: [
        'Look for two mods hooking the same function and disable one of them.',
        'Update the mods involved.'
      ]
    },
    'mod-crash': {
      title: 'The crash comes directly from a mod\'s code',
      c: [
        'The top frame of the call chain is inside a mod file, not the original game code. The most likely culprit is that mod itself or the data it reads.'
      ],
      f: [
        'Update the mod to the latest version and make sure it matches your game version and device architecture.',
        'Remove the mod together with its configuration files, then reinstall it cleanly.',
        'Report it to the mod author and attach the full aml_crashlog.txt.'
      ]
    }
  };

  const F = {
    'null': {
      title: 'Null pointer access or negative index',
      c: ['The fault address is very small, meaning the game read or wrote a struct member or array element through a null pointer. A null pointer usually appears because the data being looked up was not found (model, TXD, animation, handling) or a pool is full.'],
      f: ['Match the culprit function in the call chain with the categories above.', 'Think about the last change before the crash: a new mod or a replaced file.']
    },
    neg: {
      title: 'Index or value -1 used as an address',
      c: ['The fault address is a very large number derived from a negative value. Usually an ID or index of -1 (not found) was used directly as an array index.'],
      f: ['Look for missing reference data: a model ID, TXD name or animation that is not registered.']
    },
    pattern: {
      title: 'Patterned fault address (uninitialized or freed memory)',
      c: ['The fault address is a typical pattern (for example 0x7F7F7F7F, DEADBEEF) that indicates uninitialized or freed memory.'],
      f: ['Suspect mods that hook memory or objects that were already deleted. Disable the newest mods.']
    },
    prot: {
      title: 'Writing to protected memory (SEGV_ACCERR)',
      c: ['The code tried to write to a read-only area, for example patching code or data without changing memory permissions, or a patch address is wrong because the game version does not match.'],
      f: ['Make sure the patching mod is compatible with your game version.', 'Update or remove the most recently added patching mod.']
    },
    wild: {
      title: 'Wild pointer (invalid address)',
      c: ['The game accessed an unmapped address. Common causes: a corrupted pointer because memory was overwritten, an object that was already deleted, or wrong file data.'],
      f: ['Look at the caller chain, then test by removing recently installed mods.']
    }
  };

  g.CRASH_KB_EN = { rules: R, fault: F };
})(typeof window !== 'undefined' ? window : globalThis);

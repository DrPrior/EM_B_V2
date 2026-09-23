================================================================================
 EM KNOWLEDGE ASSISTANT — Installation from this USB drive
 Version 0.4.0 (Windows)
================================================================================

 (Maintainer: keep this version in step with electron/package.json and the
 installer file name below.)


WHAT THIS IS
------------
A private knowledge assistant that runs entirely on your own computer. Your
questions and documents never leave the machine — the language models, the
database, and the document graph all run locally.


BEFORE YOU START — please read
------------------------------
This computer should already have been prepared for you: Ollama and the
language models installed ahead of time. If so, setup runs entirely from this
USB drive and needs no internet at all.

You need:

  * Windows 10 or 11, 64-bit
  * About 40 GB of free disk space
  * Permission to install software. If this is a work-managed computer, check
    with IT first — the app must be code-signed for your machines to allow it.
  * Time. First-time setup takes roughly 10-20 minutes. You can leave it
    running.

Leave this USB drive plugged in for the whole of first-time setup. The app
reads its prepared data from it. Once setup finishes you can remove the drive
and it is never needed again.

If the computer was NOT prepared in advance, setup still works, but it has to
download Ollama and about 10 GB of language models — so it needs an internet
connection and takes 30-60 minutes instead. Everything else is the same, and
the app is fully offline once setup finishes either way.


INSTALLING
----------
1. Plug in the USB drive and open it in File Explorer.

2. Double-click:

       EM Knowledge Assistant-Setup-0.4.0.exe

3. Choose an install location (the default is fine) and let it install.

4. Launch "EM Knowledge Assistant" from the Start menu. A setup window opens
   and walks through eight steps on its own:

       Detect hardware -> Ollama -> Language models -> Database engine ->
       Application -> Source documents -> Knowledge graph -> Start assistant

   Just watch it. Each step shows its own progress. On a prepared computer the
   first three steps go by quickly — they find what they need already there and
   move on.

5. When setup finishes, the assistant opens and you can start asking questions.


AFTER SETUP
-----------
Open "EM Knowledge Assistant" from the Start menu like any other program. It
takes 30-60 seconds to start up while the local database and services come
online. No internet needed.

Ollama starts automatically in the background; the assistant starts and stops
the database and its own service for you. Leave them alone — the app manages
them.


WHAT'S ON THIS DRIVE
--------------------
  EM Knowledge Assistant-Setup-0.4.0.exe   The installer — start here.

  assets\                                  Prepared data the setup reads (the
                                           application, the database engine, the
                                           document collection, and the prebuilt
                                           knowledge graph). Do not rename, move,
                                           or open these — setup finds them
                                           automatically.

  explainer\index.html                     Technical documentation of how the
                                           system works. Open in any browser.
                                           For maintainers, not needed to use
                                           the app.

  TARGET_MACHINE_PREP.md                   How to prepare a computer before
                                           handing over the drive. For IT /
                                           whoever sets machines up.

  README.txt                               This file.


IF SOMETHING GOES WRONG
-----------------------
"Blocked by your system administrator" / the installer won't run
    The app isn't code-signed for your organization's machines yet. This is a
    policy block that Administrator rights do NOT bypass — contact whoever gave
    you the drive; it needs a signed build.

"Setup files not found"
    The USB drive was unplugged, or the folder was moved. Plug the drive back
    in and try again. If it still can't find it, a window titled "Select the
    setup folder from the USB drive" appears — choose the "assets" folder on
    the USB drive. ("That folder doesn't contain the setup files" means a
    different folder was picked.)

"Checksum mismatch for <file> — the USB copy may be corrupt"
    A file on the drive is damaged. The drive needs to be re-made; contact
    whoever gave it to you.

"Ollama is installed but could not be started automatically"
    Open Ollama from the Start menu and give it a few seconds — its icon
    appears in the system tray (bottom-right, near the clock). Then click
    Retry.

"Ollama needs to restart to apply required settings"
    Find the Ollama icon in the system tray (bottom-right, near the clock),
    quit it, open Ollama again from the Start menu, then click Retry.

Setup stalls or fails partway
    Close the app and open it again. Every step is safe to repeat — it skips
    whatever already finished and resumes from there.

Nothing happens when I ask a question
    The models need a moment on the first question after startup. If it stays
    stuck, quit the app and reopen it.

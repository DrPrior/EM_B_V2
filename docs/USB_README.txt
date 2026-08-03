================================================================================
 EM KNOWLEDGE ASSISTANT — Installation from this USB drive
 Version 0.2.0 (Windows)
================================================================================

WHAT THIS IS
------------
A private knowledge assistant that runs entirely on your own computer. Your
questions and documents never leave the machine — the language models and the
document graph all run locally.


BEFORE YOU START — please read
------------------------------
This computer should already have been prepared for you: Docker, Ollama, and
the language models installed ahead of time. If so, setup runs entirely from
this USB drive and needs no internet at all.

You need:

  * Windows 10 or 11, 64-bit
  * About 40 GB of free disk space
  * Permission to install software (administrator rights). If this is a
    work-managed computer, check with IT first.
  * Time. First-time setup takes roughly 10-20 minutes. You can leave it
    running.

Leave this USB drive plugged in for the whole of first-time setup. The app
reads about 1 GB of prepared data from it. Once setup finishes you can remove
the drive and it is never needed again.

If the computer was NOT prepared in advance, setup still works, but it has to
download Docker, Ollama, and about 10 GB of language models — so it needs an
internet connection and takes 30-60 minutes instead. Everything else is the
same, and the app is fully offline once setup finishes either way.


INSTALLING
----------
1. Plug in the USB drive and open it in File Explorer.

2. Double-click:

       EM Knowledge Assistant-Setup-0.2.0.exe

3. Windows will warn you: "Windows protected your PC" (SmartScreen). This is
   expected — the installer is not code-signed yet. Click "More info", then
   "Run anyway".

4. Choose an install location (the default is fine) and let it install.

5. Launch "EM Knowledge Assistant" from the Start menu. A setup window opens
   and walks through eight steps on its own:

       Graphics check -> Docker -> Ollama -> Language models -> Application
       image -> Source documents -> Knowledge graph -> Start

   Just watch it. Each step shows its own progress. On a prepared computer the
   first four steps go by quickly — they find what they need already there and
   move on.

6. IMPORTANT — if Docker Desktop asks to restart your computer, restart, then
   open "EM Knowledge Assistant" again. Setup picks up exactly where it left
   off — nothing is lost and nothing needs redoing. (On a prepared computer
   this should not come up.)

7. When setup finishes, the assistant opens and you can start asking
   questions.


AFTER SETUP
-----------
Open "EM Knowledge Assistant" from the Start menu like any other program. It
takes 30-60 seconds to start up while the background services come online.
No internet needed.

Docker Desktop and Ollama are installed alongside it and start automatically.
Leave them alone — the assistant manages them.


WHAT'S ON THIS DRIVE
--------------------
  EM Knowledge Assistant-Setup-0.2.0.exe   The installer — start here.

  assets\                                  Prepared data the setup reads
                                           (the application, the document
                                           collection, and the prebuilt
                                           knowledge graph). Do not rename,
                                           move, or open these — setup finds
                                           them automatically.

  explainer\index.html                     Technical documentation of how the
                                           system works. Open in any browser.
                                           For maintainers, not needed to use
                                           the app.

  README.txt                               This file.


IF SOMETHING GOES WRONG
-----------------------
"Setup can't find the assets folder"
    The USB drive was unplugged, or the folder was moved. Plug the drive back
    in and click Retry. If it still can't find it, a folder picker appears —
    select the "assets" folder on the USB drive.

"Checksum mismatch — the USB copy may be corrupt"
    A file on the drive is damaged. The drive needs to be re-made; contact
    whoever gave it to you.

"Ollama is installed but is not running"
    Open Ollama from the Start menu and give it a few seconds — its icon
    appears in the system tray (bottom-right, near the clock). Then click
    Retry.

"Ollama needs to restart"
    Find the Ollama icon in the system tray (bottom-right, near the clock),
    quit it, open Ollama again from the Start menu, then click Retry.

Setup stalls or fails partway
    Close the app and open it again. Every step is safe to repeat — it skips
    whatever already finished and resumes from there.

Nothing happens when I ask a question
    The models need a moment on the first question after startup. If it stays
    stuck, quit the app and reopen it.

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
You need:

  * Windows 10 or 11, 64-bit
  * About 40 GB of free disk space
  * An internet connection FOR THE FIRST RUN ONLY (about 10 GB is downloaded:
    Docker Desktop, Ollama, and the language models). After setup, the app
    works completely offline.
  * Permission to install software (administrator rights). If this is a
    work-managed computer, check with IT first.
  * Time. First-time setup takes roughly 30-60 minutes, mostly downloading.
    You can leave it running.

Leave this USB drive plugged in for the whole of first-time setup. The app
reads about 1 GB of prepared data from it. Once setup finishes you can remove
the drive and it is never needed again.


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

   Just watch it. Each step shows its own progress.

6. IMPORTANT — Docker Desktop may ask to restart your computer. If it does:
   restart, then open "EM Knowledge Assistant" again. Setup picks up exactly
   where it left off — nothing is lost and nothing needs redoing.

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

"Ollama needs to restart"
    Find the Ollama icon in the system tray (bottom-right, near the clock),
    quit it, open Ollama again from the Start menu, then click Retry.

Setup stalls or fails partway
    Close the app and open it again. Every step is safe to repeat — it skips
    whatever already finished and resumes from there.

Nothing happens when I ask a question
    The models need a moment on the first question after startup. If it stays
    stuck, quit the app and reopen it.

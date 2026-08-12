'use strict';

/**
 * Ensure the API image for the *current* manifest version is present before the
 * subsequent-launch fast-path start.
 *
 * The fast path (`supervisor.quickStart`) brings the stack up with
 * `emb-hybrid-api:${APP_VERSION}` but never loads an image — that only happens
 * during first-run provisioning. When the app is updated in place (new bundled
 * image version) the first-run marker still exists, so launches take the fast
 * path, yet the new image was never loaded: `compose up` then references a tag
 * that isn't present and the API container never starts, surfacing only as a
 * health timeout. Detect that here and load the new image from the USB assets,
 * prompting for the drive if it isn't mounted.
 *
 * Dependencies are injected so this is testable without Electron; main.js wires
 * in the real `docker` / `assets` / `resolveAssetsDir` and its progress + error
 * senders.
 *
 * @param {{image:{version:string, sha256:string}}} manifest Parsed asset manifest.
 * @param {object} deps
 * @param {{imageExists:(tag:string)=>Promise<boolean>, loadImage:(tar:string, onLine?:Function)=>Promise<void>}} deps.docker
 * @param {{assetPath:(dir:string, manifest:object, key:string)=>string, verify:(file:string, sha:string)=>Promise<boolean>}} deps.assets
 * @param {(manifest:object)=>Promise<string|null>} deps.resolveAssetsDir Returns the
 *   USB assets dir, or null if the user declined / it isn't available.
 * @param {(e:{step:string, status:string, message?:string})=>void} deps.emit Progress sink.
 * @param {(message:string)=>void} deps.onError User-facing error sink.
 * @returns {Promise<boolean>} false when the image is missing and couldn't be
 *   loaded (a user-facing message has already been sent via `onError`).
 */
async function ensureImageForVersion(manifest, deps) {
  const { docker, assets, resolveAssetsDir, emit, onError } = deps;
  const tag = `emb-hybrid-api:${manifest.image.version}`;
  if (await docker.imageExists(tag)) return true;

  emit({ step: 'image', status: 'active',
    message: `Loading the updated application image (${manifest.image.version})…` });
  const assetsDir = await resolveAssetsDir(manifest);
  if (!assetsDir) {
    onError(
      `This update (version ${manifest.image.version}) needs the USB drive to finish ` +
      'installing. Plug it in and reopen the app.');
    return false;
  }
  const tar = assets.assetPath(assetsDir, manifest, 'image');
  await assets.verify(tar, manifest.image.sha256);
  await docker.loadImage(tar, (l) => emit({ step: 'image', status: 'active', message: l }));
  emit({ step: 'image', status: 'done', message: 'Application image ready.' });
  return true;
}

module.exports = { ensureImageForVersion };

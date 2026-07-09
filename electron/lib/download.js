'use strict';

/**
 * Streaming HTTP(S) downloader with progress reporting, redirect handling,
 * resume-free caching, and optional SHA-256 verification. Used by the wizard to
 * fetch installers and the heavy release assets (image tar, snapshot, corpus).
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

/**
 * Download `url` to `destPath`, reporting progress as a fraction (0..1) plus
 * transferred/total bytes. Follows redirects. Writes to a .part file and renames
 * on success so a crash never leaves a truncated file looking complete.
 *
 * @param {(p:{fraction:number|null, transferred:number, total:number|null})=>void} onProgress
 * @returns {Promise<string>} the destPath
 */
function downloadFile(url, destPath, onProgress = () => {}, redirectsLeft = 5) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    const lib = url.startsWith('http:') ? http : https;
    const req = lib.get(url, (res) => {
      const { statusCode, headers } = res;
      if (statusCode >= 300 && statusCode < 400 && headers.location) {
        res.resume();
        if (redirectsLeft <= 0) return reject(new Error(`Too many redirects for ${url}`));
        const next = new URL(headers.location, url).toString();
        return resolve(downloadFile(next, destPath, onProgress, redirectsLeft - 1));
      }
      if (statusCode !== 200) {
        res.resume();
        return reject(new Error(`GET ${url} failed: HTTP ${statusCode}`));
      }
      const total = headers['content-length'] ? parseInt(headers['content-length'], 10) : null;
      let transferred = 0;
      const partPath = `${destPath}.part`;
      const out = fs.createWriteStream(partPath);
      res.on('data', (chunk) => {
        transferred += chunk.length;
        onProgress({ fraction: total ? transferred / total : null, transferred, total });
      });
      res.pipe(out);
      out.on('finish', () => out.close(() => {
        fs.renameSync(partPath, destPath);
        resolve(destPath);
      }));
      out.on('error', reject);
    });
    req.on('error', reject);
  });
}

/** Compute the SHA-256 hex digest of a file. */
function sha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (d) => hash.update(d));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

module.exports = { downloadFile, sha256 };

'use strict';

/**
 * Node port of src/services/ollama_bootstrap.py:_parse_modelfile.
 *
 * Ollama's modern /api/create no longer accepts a raw Modelfile string, so both
 * the API bootstrap and this wizard parse the Modelfile into the structured
 * SYSTEM + PARAMETER fields /api/create wants. FROM is ignored — the caller
 * supplies the base model explicitly so the pulled base and the variant's `from`
 * stay in lockstep. Keep this in sync with the Python version.
 */

function stripQuotes(v) {
  if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) {
    return v.slice(1, -1);
  }
  return v;
}

function coerceParam(raw) {
  const v = stripQuotes(raw);
  if (/^-?\d+$/.test(v)) return parseInt(v, 10);
  if (/^-?\d*\.\d+$/.test(v)) return parseFloat(v);
  return v;
}

/** Read a directive value that may be a triple-quoted multi-line block. */
function readBlock(rest, lines, i) {
  if (rest.startsWith('"""')) {
    let body = rest.slice(3);
    if (body.endsWith('"""') && body.length >= 3) return [body.slice(0, -3), i + 1];
    const collected = [body];
    let j = i + 1;
    while (j < lines.length) {
      const q = lines[j].indexOf('"""');
      if (q >= 0) {
        collected.push(lines[j].slice(0, q));
        return [collected.join('\n'), j + 1];
      }
      collected.push(lines[j]);
      j += 1;
    }
    return [collected.join('\n'), j];
  }
  return [stripQuotes(rest), i + 1];
}

/**
 * @param {string} text Modelfile contents.
 * @returns {{system: string|null, parameters: Object}}
 */
function parseModelfile(text) {
  let system = null;
  const parameters = {};
  const lines = text.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const stripped = lines[i].trim();
    if (!stripped || stripped.startsWith('#')) { i += 1; continue; }
    const sp = stripped.indexOf(' ');
    const keyword = (sp < 0 ? stripped : stripped.slice(0, sp)).toUpperCase();
    const rest = (sp < 0 ? '' : stripped.slice(sp + 1)).trim();
    if (keyword === 'PARAMETER') {
      const ks = rest.indexOf(' ');
      const key = ks < 0 ? rest : rest.slice(0, ks);
      const value = coerceParam((ks < 0 ? '' : rest.slice(ks + 1)).trim());
      if (key in parameters) {
        parameters[key] = Array.isArray(parameters[key])
          ? [...parameters[key], value]
          : [parameters[key], value];
      } else {
        parameters[key] = value;
      }
      i += 1;
    } else if (keyword === 'SYSTEM') {
      [system, i] = readBlock(rest, lines, i);
    } else {
      i += 1; // FROM / TEMPLATE / LICENSE etc.
    }
  }
  return { system, parameters };
}

module.exports = { parseModelfile };

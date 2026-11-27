// Build script of the fixture web application.
//
// The real web slice is built with Vite; the fixture only has to produce a
// `dist/` directory so the nginx image has something to serve.

import { mkdirSync, writeFileSync } from 'node:fs';

mkdirSync('dist', { recursive: true });

writeFileSync(
  'dist/index.html',
  [
    '<!doctype html>',
    '<html lang="en">',
    '  <head>',
    '    <meta charset="utf-8" />',
    '    <meta name="viewport" content="width=device-width, initial-scale=1" />',
    '    <title>NEXUS AGENT OS — container fixture</title>',
    '  </head>',
    '  <body>',
    '    <div id="root">NEXUS AGENT OS — container fixture</div>',
    '  </body>',
    '</html>',
    '',
  ].join('\n'),
);

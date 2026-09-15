# amp-case-videos

One voiced automation case video a day for Automation Matrix Pro.

`case.py` asks Claude for a case, voices it with Kokoro, renders `case.html` at 9:16 with headless Chrome, mixes the `ambience.py` drone under the voice, uploads to the site and requests approval. The approval email (site/am-cases.php, deployed in the WordPress sandbox) posts to Instagram and Facebook on click.

Test without Claude: `python case.py --case sample-case.json --dry-run`

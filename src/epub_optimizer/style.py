CANONICAL_CSS = """\
@namespace epub "http://www.idpf.org/2007/ops";

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
}

body {
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
}

p {
  margin: 0 0 0.75em;
  text-align: justify;
}

p.eo-body {
  text-indent: 0;
}

p.eo-first {
  text-indent: 1em;
}

p.eo-front-body {
  margin: 0;
  text-align: justify;
  text-indent: 1em;
}

p.eo-front-list-item {
  margin: 0.4em 0;
  text-align: center;
  text-indent: 0;
}

p.eo-front-section {
  margin: 1.4em 0 0.5em;
  font-weight: bold;
  text-align: center;
  text-indent: 0;
  text-transform: uppercase;
}

.eo-metadata-page {
  margin: 3em 0 0;
  text-align: center;
}

h1.eo-metadata-title,
p.eo-metadata-title {
  margin: 1em 0;
  font-size: 1.1em;
  line-height: 1.3;
  font-weight: bold;
  text-align: center;
  text-indent: 0;
}

p.eo-metadata-line {
  margin: 0.35em 0;
  font-size: 0.9em;
  line-height: 1.3;
  text-align: center;
  text-indent: 0;
}

h1,
h2,
h3,
h4,
h5,
h6 {
  break-after: avoid;
  page-break-after: avoid;
  hyphens: none;
}

h1.eo-chapter,
h2.eo-chapter,
h3.eo-chapter {
  margin: 2em 0 3em;
  font-size: 1.2em;
  line-height: 1.3;
  font-weight: bold;
  text-align: center;
}

h1.eo-part,
h2.eo-part,
h3.eo-part {
  margin: 3em 0 2em;
  font-size: 1.4em;
  line-height: 1.3;
  font-weight: normal;
  text-align: center;
}

h1.eo-front,
h2.eo-front,
h3.eo-front,
h4.eo-front,
h5.eo-front,
h6.eo-front {
  margin: 3em 0 2em;
  font-size: 1em;
  font-weight: bold;
  text-align: center;
}

h1.eo-section,
h2.eo-section,
h3.eo-section,
h4.eo-section,
h5.eo-section,
h6.eo-section {
  margin: 2em 0 1em;
  font-size: 1.05em;
  font-weight: normal;
  text-align: center;
}

p.eo-centered,
div.eo-centered,
blockquote.eo-centered {
  margin: 1em 0;
  text-indent: 0;
  text-align: center;
}

p.eo-right,
div.eo-right,
blockquote.eo-right {
  margin: 0;
  text-indent: 0;
  text-align: right;
}

.eo-dedication {
  margin: 4em 0 0;
  text-align: center;
}

.eo-title-page {
  margin: 18% 0 0;
  text-align: center;
}

h1.eo-title-main,
p.eo-title-main {
  margin: 0 0 2.5em;
  font-size: 1.6em;
  line-height: 1.25;
  font-weight: bold;
  text-align: center;
  text-indent: 0;
  letter-spacing: 0;
}

p.eo-title-credit-label {
  margin: 0 0 0.6em;
  font-size: 0.85em;
  line-height: 1.3;
  text-align: center;
  text-indent: 0;
  text-transform: uppercase;
}

p.eo-title-credit {
  margin: 0 0 2.5em;
  font-size: 1.15em;
  line-height: 1.3;
  text-align: center;
  text-indent: 0;
}

p.eo-title-author {
  margin: 3em 0 5em;
  font-size: 1.25em;
  line-height: 1.3;
  text-align: center;
  text-indent: 0;
}

p.eo-title-publisher {
  margin: 0.2em 0;
  font-size: 0.85em;
  line-height: 1.25;
  text-align: center;
  text-indent: 0;
}

.eo-toc {
  margin: 1em 0;
  text-align: center;
}

h1.eo-toc-heading,
h2.eo-toc-heading,
h3.eo-toc-heading {
  margin: 2em 0 3em;
  font-size: 1.2em;
  line-height: 1.3;
  font-weight: bold;
  text-align: center;
}

p.eo-toc-entry,
div.eo-toc-entry {
  margin: 1em 0 0;
  font-size: 0.9em;
  line-height: 1.4;
  text-align: center;
  text-indent: 0;
}

p.eo-toc-part,
div.eo-toc-part {
  margin: 1em 0 0;
  font-size: 1em;
  line-height: 1.5;
  text-align: center;
  text-indent: 0;
  font-weight: bold;
  text-transform: uppercase;
}

p.eo-toc-chapter,
div.eo-toc-chapter {
  margin: 0;
  font-size: 0.9em;
  line-height: 1.4;
  text-align: center;
  text-indent: 0;
}

p.eo-scene-break {
  margin: 1.5em 0;
  text-align: center;
  text-indent: 0;
}

div.eo-extract,
p.eo-extract,
blockquote.eo-blockquote,
blockquote {
  margin: 1em 1.4em;
  text-align: justify;
  text-indent: 0;
}

.eo-extract p,
blockquote p,
p.eo-blockquote {
  text-indent: 0;
}

p.eo-caption,
figcaption.eo-caption {
  margin: 0.5em 0 1em;
  text-align: center;
  font-style: italic;
  text-indent: 0;
}

div.eo-image,
figure.eo-image,
p.eo-image {
  margin: 1em 0;
  text-align: center;
  text-indent: 0;
}

img {
  max-width: 100%;
  max-height: 100%;
}

div.eo-poetry,
p.eo-poetry,
pre.eo-poetry {
  margin: 1em 0 1em 2em;
  text-align: left;
  white-space: pre-wrap;
  text-indent: 0;
}

div.eo-hanging,
p.eo-hanging {
  margin-left: 1em;
  text-align: justify;
  text-indent: -1em;
}

aside.eo-footnote,
div.eo-footnote,
p.eo-footnote {
  margin-top: 1em;
  font-size: 0.9em;
  text-align: justify;
  text-indent: 0;
}

ol,
ul {
  margin: 1em 0;
  text-align: justify;
}

ol.eo-list,
ul.eo-list {
  margin: 1em 0;
}

a {
  color: inherit;
  text-decoration: none;
}

em,
i {
  font-style: italic;
}

strong,
b {
  font-weight: bold;
}

sup {
  vertical-align: super;
  font-size: 0.75em;
  line-height: 0;
}

sub {
  vertical-align: sub;
  font-size: 0.75em;
  line-height: 0;
}

.eo-underline {
  text-decoration: underline;
}

.eo-strike {
  text-decoration: line-through;
}

.eo-overline {
  text-decoration: overline;
}

.eo-smallcaps {
  font-variant: small-caps;
}

span.eo-smallcaps {
  font-variant: small-caps;
}
"""

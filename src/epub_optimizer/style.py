CANONICAL_CSS = """\
@namespace epub "http://www.idpf.org/2007/ops";

html,
body {
  margin: 0;
  padding: 0;
}

body {
  font-family: inherit;
}

p {
  margin: 0;
  text-align: justify;
}

p.eo-body {
  text-indent: 1em;
}

p.eo-first {
  text-indent: 0;
}

h1.eo-chapter,
h2.eo-chapter {
  margin: 2em 0 3em;
  font-size: 1.2em;
  line-height: 1.3;
  font-weight: bold;
  text-align: left;
  break-after: avoid;
  page-break-after: avoid;
}

h1.eo-part,
h2.eo-part {
  margin: 3em 0 2em;
  font-size: 1.4em;
  line-height: 1.3;
  font-weight: normal;
  text-align: center;
  break-after: avoid;
  page-break-after: avoid;
}

h1.eo-front,
h2.eo-front,
h3.eo-front {
  margin: 3em 0 2em;
  font-size: 1em;
  font-weight: bold;
  text-align: center;
  break-after: avoid;
  page-break-after: avoid;
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
  text-align: left;
  break-after: avoid;
  page-break-after: avoid;
}

.eo-centered {
  text-align: center;
}

.eo-right {
  text-align: right;
}

.eo-extract,
blockquote {
  margin: 1em 1.4em;
}

.eo-extract p,
blockquote p {
  text-indent: 0;
}

.eo-caption {
  margin: 0.5em 0 1em;
  text-align: center;
  font-style: italic;
}

.eo-image {
  margin: 1em 0;
  text-align: center;
}

img {
  max-width: 100%;
  max-height: 100%;
}

ol,
ul {
  text-align: justify;
}

a {
  color: inherit;
}
"""

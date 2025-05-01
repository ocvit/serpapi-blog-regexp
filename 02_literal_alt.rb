require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

EXAMPLES = {
  "literal-alt/sherlock-en" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt"
    },
    patterns: {
      ruby: 'Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty',
      re2: '(Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty)',
      rust: 'Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty'
    },
    validations: {
      count: {
        :* => 714
      }
    }
  },
  "literal-alt/sherlock-casei-en" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt"
    },
    patterns: {
      ruby: '(?i)Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty',
      re2: '(?i:(Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty))',
      rust: '(?i)Sherlock Holmes|John Watson|Irene Adler|Inspector Lestrade|Professor Moriarty'
    },
    validations: {
      count: {
        :* => 725
      }
    }
  },
  "literal-alt/sherlock-ru" => {
    haystack: {
      path: "./data/opensubtitles/ru-sampled.txt"
    },
    patterns: {
      ruby: 'Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти',
      re2: '(Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти)',
      rust: 'Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти'
    },
    validations: {
      count: {
        :* => 899
      }
    }
  },
  "literal-alt/sherlock-casei-ru" => {
    haystack: {
      path: "./data/opensubtitles/ru-sampled.txt"
    },
    patterns: {
      ruby: '(?i)Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти',
      re2: '(?i:(Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти))',
      rust: '(?i)Шерлок Холмс|Джон Уотсон|Ирен Адлер|инспектор Лестрейд|профессор Мориарти'
    },
    validations: {
      count: {
        :* => 971
      }
    }
  },
  "literal-alt/sherlock-zh" => {
    haystack: {
      path: "./data/opensubtitles/zh-sampled.txt"
    },
    patterns: {
      ruby: '夏洛克·福尔摩斯|约翰华生|阿德勒|雷斯垂德|莫里亚蒂教授',
      re2: '(夏洛克·福尔摩斯|约翰华生|阿德勒|雷斯垂德|莫里亚蒂教授)',
      rust: '夏洛克·福尔摩斯|约翰华生|阿德勒|雷斯垂德|莫里亚蒂教授'
    },
    validations: {
      count: {
        :* => 207
      }
    }
  },
}

EXAMPLES.each do |title, example|
  puts "\n-- [#{title}]"

  haystack = prepare_haystack(example)
  regexps = prepare_regexps(example)

  validate_matches!(example, haystack, regexps)

  ruby_regexp, re2_regexp, rust_regexp = regexps.fetch_values(:ruby, :re2, :rust)

  Benchmark.ips do |x|
    x.report("ruby") do
      ruby_scan(haystack, ruby_regexp)
    end

    x.report("re2") do
      re2_scan(haystack, re2_regexp)
    end

    x.report("rust/regex") do
      rust_scan(haystack, rust_regexp)
    end

    x.compare!
  end
end


# [Ubuntu 24.04.1 LTS | DigitalOcean CPU-optimized Intel 4 vCPUs / 8 GiB]
#
# -- [literal-alt/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    17.000 i/100ms
#                  re2    55.000 i/100ms
#           rust/regex   642.000 i/100ms
# Calculating -------------------------------------
#                 ruby    175.748 (± 0.0%) i/s    (5.69 ms/i) -    884.000 in   5.029956s
#                  re2    552.693 (± 0.7%) i/s    (1.81 ms/i) -      2.805k in   5.075420s
#           rust/regex      6.407k (± 0.4%) i/s  (156.08 μs/i) -     32.100k in   5.010115s

# Comparison:
#           rust/regex:     6407.2 i/s
#                  re2:      552.7 i/s - 11.59x  slower
#                 ruby:      175.7 i/s - 36.46x  slower


# -- [literal-alt/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     8.000 i/100ms
#                  re2    55.000 i/100ms
#           rust/regex   289.000 i/100ms
# Calculating -------------------------------------
#                 ruby     83.630 (± 0.0%) i/s   (11.96 ms/i) -    424.000 in   5.070034s
#                  re2    550.273 (± 0.4%) i/s    (1.82 ms/i) -      2.805k in   5.097541s
#           rust/regex      2.896k (± 0.5%) i/s  (345.30 μs/i) -     14.739k in   5.089453s

# Comparison:
#           rust/regex:     2896.1 i/s
#                  re2:      550.3 i/s - 5.26x  slower
#                 ruby:       83.6 i/s - 34.63x  slower


# -- [literal-alt/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     2.000 i/100ms
#                  re2    32.000 i/100ms
#           rust/regex   229.000 i/100ms
# Calculating -------------------------------------
#                 ruby     29.989 (± 0.0%) i/s   (33.35 ms/i) -    150.000 in   5.001989s
#                  re2    324.299 (± 0.6%) i/s    (3.08 ms/i) -      1.632k in   5.032606s
#           rust/regex      2.292k (± 0.5%) i/s  (436.34 μs/i) -     11.679k in   5.096204s

# Comparison:
#           rust/regex:     2291.8 i/s
#                  re2:      324.3 i/s - 7.07x  slower
#                 ruby:       30.0 i/s - 76.42x  slower


# -- [literal-alt/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2    31.000 i/100ms
#           rust/regex    62.000 i/100ms
# Calculating -------------------------------------
#                 ruby     12.274 (± 0.0%) i/s   (81.47 ms/i) -     62.000 in   5.051406s
#                  re2    314.334 (± 0.6%) i/s    (3.18 ms/i) -      1.581k in   5.029859s
#           rust/regex    627.731 (± 0.6%) i/s    (1.59 ms/i) -      3.162k in   5.037377s

# Comparison:
#           rust/regex:      627.7 i/s
#                  re2:      314.3 i/s - 2.00x  slower
#                 ruby:       12.3 i/s - 51.14x  slower


# -- [literal-alt/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     8.000 i/100ms
#                  re2    73.000 i/100ms
#           rust/regex   995.000 i/100ms
# Calculating -------------------------------------
#                 ruby     84.924 (± 0.0%) i/s   (11.78 ms/i) -    432.000 in   5.087020s
#                  re2    737.563 (± 0.1%) i/s    (1.36 ms/i) -      3.723k in   5.047722s
#           rust/regex     10.016k (± 0.4%) i/s   (99.84 μs/i) -     50.745k in   5.066428s

# Comparison:
#           rust/regex:    10016.1 i/s
#                  re2:      737.6 i/s - 13.58x  slower
#                 ruby:       84.9 i/s - 117.94x  slower
#
# =========================================================================================
#
# [macOS 15.4.1 | M4 Max]
#
# -- [literal-alt/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    36.000 i/100ms
#                  re2    62.000 i/100ms
#           rust/regex   954.000 i/100ms
# Calculating -------------------------------------
#                 ruby    361.658 (± 2.2%) i/s    (2.77 ms/i) -      1.836k in   5.079429s
#                  re2    618.369 (± 3.4%) i/s    (1.62 ms/i) -      3.100k in   5.019205s
#           rust/regex      9.408k (± 2.9%) i/s  (106.29 μs/i) -     47.700k in   5.074781s

# Comparison:
#           rust/regex:     9407.8 i/s
#                  re2:      618.4 i/s - 15.21x  slower
#                 ruby:      361.7 i/s - 26.01x  slower


# -- [literal-alt/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    15.000 i/100ms
#                  re2    63.000 i/100ms
#           rust/regex   444.000 i/100ms
# Calculating -------------------------------------
#                 ruby    155.217 (± 2.6%) i/s    (6.44 ms/i) -    780.000 in   5.028094s
#                  re2    615.981 (± 4.4%) i/s    (1.62 ms/i) -      3.087k in   5.021288s
#           rust/regex      4.473k (± 1.9%) i/s  (223.54 μs/i) -     22.644k in   5.063732s

# Comparison:
#           rust/regex:     4473.4 i/s
#                  re2:      616.0 i/s - 7.26x  slower
#                 ruby:      155.2 i/s - 28.82x  slower


# -- [literal-alt/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     5.000 i/100ms
#                  re2    36.000 i/100ms
#           rust/regex   405.000 i/100ms
# Calculating -------------------------------------
#                 ruby     51.582 (± 0.0%) i/s   (19.39 ms/i) -    260.000 in   5.040710s
#                  re2    367.814 (± 1.6%) i/s    (2.72 ms/i) -      1.872k in   5.090818s
#           rust/regex      4.168k (± 2.0%) i/s  (239.91 μs/i) -     21.060k in   5.054633s

# Comparison:
#           rust/regex:     4168.2 i/s
#                  re2:      367.8 i/s - 11.33x  slower
#                 ruby:       51.6 i/s - 80.81x  slower


# -- [literal-alt/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     2.000 i/100ms
#                  re2    34.000 i/100ms
#           rust/regex   128.000 i/100ms
# Calculating -------------------------------------
#                 ruby     21.426 (± 0.0%) i/s   (46.67 ms/i) -    108.000 in   5.041791s
#                  re2    355.939 (± 3.1%) i/s    (2.81 ms/i) -      1.802k in   5.068000s
#           rust/regex      1.334k (± 4.9%) i/s  (749.46 μs/i) -      6.656k in   5.000596s

# Comparison:
#           rust/regex:     1334.3 i/s
#                  re2:      355.9 i/s - 3.75x  slower
#                 ruby:       21.4 i/s - 62.27x  slower


# -- [literal-alt/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    13.000 i/100ms
#                  re2    81.000 i/100ms
#           rust/regex     1.296k i/100ms
# Calculating -------------------------------------
#                 ruby    138.440 (± 5.1%) i/s    (7.22 ms/i) -    702.000 in   5.091382s
#                  re2    808.777 (± 1.1%) i/s    (1.24 ms/i) -      4.050k in   5.008206s
#           rust/regex     12.779k (± 1.7%) i/s   (78.25 μs/i) -     64.800k in   5.072295s

# Comparison:
#           rust/regex:    12778.9 i/s
#                  re2:      808.8 i/s - 15.80x  slower
#                 ruby:      138.4 i/s - 92.31x  slower

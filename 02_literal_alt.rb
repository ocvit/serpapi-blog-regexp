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
  "literala-alt/sherlock-zh" => {
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

# [macOS | M1 Max]
#
# -- [literal-alt/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    17.000 i/100ms
#                  re2    40.000 i/100ms
#           rust/regex   654.000 i/100ms
# Calculating -------------------------------------
#                 ruby    174.272 (± 0.0%) i/s    (5.74 ms/i) -    884.000 in   5.072557s
#                  re2    360.699 (±13.0%) i/s    (2.77 ms/i) -      1.800k in   5.088376s
#           rust/regex      6.297k (± 6.3%) i/s  (158.81 μs/i) -     31.392k in   5.012077s

# Comparison:
#           rust/regex:     6296.8 i/s
#                  re2:      360.7 i/s - 17.46x  slower
#                 ruby:      174.3 i/s - 36.13x  slower


# -- [literal-alt/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     7.000 i/100ms
#                  re2    37.000 i/100ms
#           rust/regex   277.000 i/100ms
# Calculating -------------------------------------
#                 ruby     83.347 (± 4.8%) i/s   (12.00 ms/i) -    420.000 in   5.052357s
#                  re2    398.028 (± 0.5%) i/s    (2.51 ms/i) -      1.998k in   5.019882s
#           rust/regex      2.869k (± 0.5%) i/s  (348.56 μs/i) -     14.404k in   5.020739s

# Comparison:
#           rust/regex:     2869.0 i/s
#                  re2:      398.0 i/s - 7.21x  slower
#                 ruby:       83.3 i/s - 34.42x  slower


# -- [literal-alt/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     3.000 i/100ms
#                  re2    23.000 i/100ms
#           rust/regex   261.000 i/100ms
# Calculating -------------------------------------
#                 ruby     33.312 (± 0.0%) i/s   (30.02 ms/i) -    168.000 in   5.043638s
#                  re2    232.397 (± 0.4%) i/s    (4.30 ms/i) -      1.173k in   5.047501s
#           rust/regex      2.603k (± 0.6%) i/s  (384.17 μs/i) -     13.050k in   5.013604s

# Comparison:
#           rust/regex:     2603.0 i/s
#                  re2:      232.4 i/s - 11.20x  slower
#                 ruby:       33.3 i/s - 78.14x  slower


# -- [literal-alt/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2    22.000 i/100ms
#           rust/regex    78.000 i/100ms
# Calculating -------------------------------------
#                 ruby     14.065 (± 0.0%) i/s   (71.10 ms/i) -     71.000 in   5.048110s
#                  re2    227.820 (± 0.9%) i/s    (4.39 ms/i) -      1.144k in   5.021997s
#           rust/regex    790.461 (± 0.5%) i/s    (1.27 ms/i) -      3.978k in   5.032615s

# Comparison:
#           rust/regex:      790.5 i/s
#                  re2:      227.8 i/s - 3.47x  slower
#                 ruby:       14.1 i/s - 56.20x  slower


# -- [literala-alt/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     9.000 i/100ms
#                  re2    50.000 i/100ms
#           rust/regex   934.000 i/100ms
# Calculating -------------------------------------
#                 ruby     94.866 (± 2.1%) i/s   (10.54 ms/i) -    477.000 in   5.029451s
#                  re2    502.701 (± 1.0%) i/s    (1.99 ms/i) -      2.550k in   5.073116s
#           rust/regex      9.371k (± 0.9%) i/s  (106.71 μs/i) -     47.634k in   5.083438s

# Comparison:
#           rust/regex:     9371.3 i/s
#                  re2:      502.7 i/s - 18.64x  slower
#                 ruby:       94.9 i/s - 98.79x  slower
#
# =========================================================================================
#

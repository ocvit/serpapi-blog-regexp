require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - regexps are not joined (alternated) to test scenario when you need to keep a reference to regexp that matched
# - ruby: can't handle string with invalid UTF-8 chars, had to run `.encode` with replacement -- outsider
# - re2: \d{20,1024} - invalid repetition size, had to set 1000 as max
# - rust set: \w, \d, \s, \b and wide scopes like [^a-zA-Z0-9_-] without additional unique patterns/suffixes, especially in
#             non-capturing (?:) groups make set SUPER slow in comparison to sequential regexps;
#             possible explanation - unicode awarness of those matchers;
#             disabling unicode improves set performance to the level of sequential regexps (roughly);
#             disabling unicode and removing regexps with wide scopes make set faster than sequential regexps

EXAMPLES = {
  "noseyparker/default" => {
    haystack: {
      path: "./data/cpython-226484e4_medium.py",
    },
    patterns_path: "./data/noseyparker/regexps_selected.txt",
    validations: {
      count: {
        :* => 1
      }
    }
  },
  "noseyparker/no-unicode" => {
    haystack: {
      path: "./data/cpython-226484e4_medium.py",
    },
    patterns_path: "./data/noseyparker/regexps_selected.txt",
    unicode: false,
    validations: {
      count: {
        :* => 1
      }
    }
  },
  "noseyparker/no-unicode-no-wide-scopes" => {
    haystack: {
      path: "./data/cpython-226484e4_medium.py",
    },
    patterns_path: "./data/noseyparker/regexps_selected_no_wide_scopes.txt",
    unicode: false,
    validations: {
      count: {
        :* => 0
      }
    }
  },
}

EXAMPLES.each do |title, example|
  puts "\n-- [#{title}]"

  haystack = prepare_haystack(example)
  haystack_valid_utf8 = haystack.encode("UTF-8", invalid: :replace, replace: "")

  regexps = prepare_regexps(example)
  sets = prepare_sets(example)

  validate_matches!(example, haystack, regexps, sets, haystack_valid_utf8)

  ruby_regexps, re2_regexps, rust_regexps = regexps.fetch_values(:ruby, :re2, :rust)
  re2_set, rust_set = sets.fetch_values(:re2_set, :rust_set)

  Benchmark.ips do |x|
    x.report("ruby") do
      ruby_regexps.map do |regexp|
        ruby_scan(haystack_valid_utf8, regexp)
      end
    end

    x.report("re2") do
      re2_regexps.map do |regexp|
        re2_scan(haystack, regexp)
      end
    end

    x.report("rust/regex") do
      rust_regexps.map do |regexp|
        rust_scan(haystack, regexp)
      end
    end

    x.report("re2 set") do
      re2_set_scan(haystack, re2_set, re2_regexps)
    end

    x.report("rust/regex set") do
      rust_set_scan(haystack, rust_set, rust_regexps)
    end

    x.compare!
  end
end


# [Ubuntu 24.04.1 LTS | DigitalOcean CPU-optimized Intel 4 vCPUs / 8 GiB]
#
# -- [noseyparker/default]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     5.000 i/100ms
#              re2 set     4.000 i/100ms
#       rust/regex set     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      2.259 (± 0.0%) i/s  (442.76 ms/i) -     12.000 in   5.313185s
#                  re2      2.229 (± 0.0%) i/s  (448.62 ms/i) -     12.000 in   5.383492s
#           rust/regex     54.259 (± 0.0%) i/s   (18.43 ms/i) -    275.000 in   5.068428s
#              re2 set     46.733 (± 0.0%) i/s   (21.40 ms/i) -    236.000 in   5.050062s
#       rust/regex set      0.179 (± 0.0%) i/s     (5.58 s/i) -      1.000 in   5.576035s

# Comparison:
#           rust/regex:       54.3 i/s
#              re2 set:       46.7 i/s - 1.16x  slower
#                 ruby:        2.3 i/s - 24.02x  slower
#                  re2:        2.2 i/s - 24.34x  slower
#       rust/regex set:        0.2 i/s - 302.55x  slower


# -- [noseyparker/no-unicode]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     5.000 i/100ms
#              re2 set     4.000 i/100ms
#       rust/regex set     6.000 i/100ms
# Calculating -------------------------------------
#                 ruby      2.261 (± 0.0%) i/s  (442.30 ms/i) -     12.000 in   5.307593s
#                  re2      2.222 (± 0.0%) i/s  (449.97 ms/i) -     12.000 in   5.399727s
#           rust/regex     58.438 (± 0.0%) i/s   (17.11 ms/i) -    295.000 in   5.048170s
#              re2 set     46.765 (± 0.0%) i/s   (21.38 ms/i) -    236.000 in   5.046541s
#       rust/regex set     63.660 (± 0.0%) i/s   (15.71 ms/i) -    324.000 in   5.089633s

# Comparison:
#       rust/regex set:       63.7 i/s
#           rust/regex:       58.4 i/s - 1.09x  slower
#              re2 set:       46.8 i/s - 1.36x  slower
#                 ruby:        2.3 i/s - 28.16x  slower
#                  re2:        2.2 i/s - 28.65x  slower


# -- [noseyparker/no-unicode-no-wide-scopes]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex    10.000 i/100ms
#              re2 set     9.000 i/100ms
#       rust/regex set    55.000 i/100ms
# Calculating -------------------------------------
#                 ruby      6.987 (± 0.0%) i/s  (143.12 ms/i) -     35.000 in   5.009224s
#                  re2      3.223 (± 0.0%) i/s  (310.31 ms/i) -     17.000 in   5.275362s
#           rust/regex    103.759 (± 1.0%) i/s    (9.64 ms/i) -    520.000 in   5.011819s
#              re2 set     94.412 (± 1.1%) i/s   (10.59 ms/i) -    477.000 in   5.053396s
#       rust/regex set    559.751 (± 0.4%) i/s    (1.79 ms/i) -      2.805k in   5.011212s

# Comparison:
#       rust/regex set:      559.8 i/s
#           rust/regex:      103.8 i/s - 5.39x  slower
#              re2 set:       94.4 i/s - 5.93x  slower
#                 ruby:        7.0 i/s - 80.11x  slower
#                  re2:        3.2 i/s - 173.70x  slower
#
# =========================================================================================
#
# [macOS 15.4.1 | M4 Max]
#
# -- [noseyparker/default]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     9.000 i/100ms
#              re2 set     5.000 i/100ms
#       rust/regex set     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      3.979 (± 0.0%) i/s  (251.33 ms/i) -     20.000 in   5.028781s
#                  re2      2.365 (± 0.0%) i/s  (422.75 ms/i) -     12.000 in   5.075375s
#           rust/regex     97.203 (± 1.0%) i/s   (10.29 ms/i) -    486.000 in   5.000010s
#              re2 set     50.838 (± 0.0%) i/s   (19.67 ms/i) -    255.000 in   5.015933s
#       rust/regex set      0.390 (± 0.0%) i/s     (2.57 s/i) -      2.000 in   5.133136s

# Comparison:
#           rust/regex:       97.2 i/s
#              re2 set:       50.8 i/s - 1.91x  slower
#                 ruby:        4.0 i/s - 24.43x  slower
#                  re2:        2.4 i/s - 41.09x  slower
#       rust/regex set:        0.4 i/s - 249.48x  slower


# -- [noseyparker/no-unicode]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex    10.000 i/100ms
#              re2 set     5.000 i/100ms
#       rust/regex set     9.000 i/100ms
# Calculating -------------------------------------
#                 ruby      3.986 (± 0.0%) i/s  (250.86 ms/i) -     20.000 in   5.017669s
#                  re2      2.394 (± 0.0%) i/s  (417.74 ms/i) -     12.000 in   5.012977s
#           rust/regex    103.309 (± 1.0%) i/s    (9.68 ms/i) -    520.000 in   5.033604s
#              re2 set     50.506 (± 2.0%) i/s   (19.80 ms/i) -    255.000 in   5.049870s
#       rust/regex set     90.103 (± 1.1%) i/s   (11.10 ms/i) -    459.000 in   5.094785s

# Comparison:
#           rust/regex:      103.3 i/s
#       rust/regex set:       90.1 i/s - 1.15x  slower
#              re2 set:       50.5 i/s - 2.05x  slower
#                 ruby:        4.0 i/s - 25.92x  slower
#                  re2:        2.4 i/s - 43.16x  slower


# -- [noseyparker/no-unicode-no-wide-scopes]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex    19.000 i/100ms
#              re2 set    10.000 i/100ms
#       rust/regex set    40.000 i/100ms
# Calculating -------------------------------------
#                 ruby     10.834 (± 0.0%) i/s   (92.30 ms/i) -     55.000 in   5.076958s
#                  re2      3.438 (± 0.0%) i/s  (290.87 ms/i) -     18.000 in   5.235939s
#           rust/regex    195.755 (± 0.5%) i/s    (5.11 ms/i) -    988.000 in   5.047323s
#              re2 set    101.849 (± 1.0%) i/s    (9.82 ms/i) -    510.000 in   5.007597s
#       rust/regex set    410.133 (± 0.7%) i/s    (2.44 ms/i) -      2.080k in   5.071830s

# Comparison:
#       rust/regex set:      410.1 i/s
#           rust/regex:      195.8 i/s - 2.10x  slower
#              re2 set:      101.8 i/s - 4.03x  slower
#                 ruby:       10.8 i/s - 37.86x  slower
#                  re2:        3.4 i/s - 119.30x  slower

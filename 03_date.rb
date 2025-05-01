require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - unicode example has been excluded as in re2 neither \d nor \s are Unicode-aware,
#   and \s being ASCII-only does impact the match count
# - selected line range differs from rebar

EXAMPLES = {
  "date/ascii" => {
    haystack: {
      path: "./data/rust-src-tools-3b0d4813.txt",
      line_start: 150_000,
      line_end: 200_000
    },
    pattern_path: "./data/date/regexp.txt",
    unicode: false,
    validations: {
      count_spans: {
        :* => 69288
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
# -- [date/ascii]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      0.583 (± 0.0%) i/s     (1.71 s/i) -      3.000 in   5.141671s
#                  re2     13.299 (± 0.0%) i/s   (75.19 ms/i) -     67.000 in   5.038107s
#           rust/regex     18.069 (± 0.0%) i/s   (55.34 ms/i) -     91.000 in   5.036226s

# Comparison:
#           rust/regex:       18.1 i/s
#                  re2:       13.3 i/s - 1.36x  slower
#                 ruby:        0.6 i/s - 30.97x  slower
#
# =========================================================================================
#
# [macOS 15.4.1 | M4 Max]
#
# -- [date/ascii]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     3.000 i/100ms
# Calculating -------------------------------------
#                 ruby      0.861 (± 0.0%) i/s     (1.16 s/i) -      5.000 in   5.804259s
#                  re2     16.080 (±12.4%) i/s   (62.19 ms/i) -     78.000 in   5.018671s
#           rust/regex     29.162 (± 3.4%) i/s   (34.29 ms/i) -    147.000 in   5.043598s

# Comparison:
#           rust/regex:       29.2 i/s
#                  re2:       16.1 i/s - 1.81x  slower
#                 ruby:        0.9 i/s - 33.85x  slower

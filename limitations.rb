require "re2"
require "rust_regexp"
require "pry"

# Ruby: \w, \d, \s are NOT unicode aware -- can be replaced with [[:alpha:]], [[:digit:]], [[:space:]], \b is OK
# RE2: \w, \d, \s, \b are NOT unicode aware, no replacement
# Rust: OK by default

def sample(name)
  result =
    begin
      yield
    rescue => error
      error.to_s
    end

  puts "#{name.ljust(30)} | #{result.inspect}"
end

def w
  haystack = "- Yes, Fräulein."

  sample("ruby \\w") { haystack.scan(/\w+/) }
  # => ["Yes", "Fr", "ulein"]

  sample("ruby [[:alpha:]]") { haystack.scan(/[[:alpha:]]+/) }
  # => ["Yes", "Fräulein"] -- ok

  sample("re2 \\w") { RE2('(\w+)').scan(haystack).to_a.flatten }
  # => ["Yes", "Fr", "ulein"]

  sample("re2 [[:alpha:]]") { RE2('([[:alpha:]]+)').scan(haystack).to_a.flatten }
  # => ["Yes", "Fr", "ulein"]

  sample("rust \\w") { RustRegexp.new('\w+').scan(haystack) }
  # => ["Yes", "Fräulein"] -- ok

  sample("rust \\w non-unicode") { RustRegexp.new('\w+', unicode: false).scan(haystack) }
  # => ["Yes", "Fr", "ulein"]
end

def d
  haystack = "0123456789٠١٢٣٤٥٦٧٨٩߀߁߂߃߄߅߆߇߈߉"

  sample("ruby \\d") { haystack.scan(/\d+/) }
  # => ["0123456789"]

  sample("ruby [[:digit:]]") { haystack.scan(/[[:digit:]]+/) }
  # => ["0123456789٠١٢٣٤٥٦٧٨٩߀߁߂߃߄߅߆߇߈߉"] -- ok

  sample("re2 \\d") { RE2('(\d+)').scan(haystack).to_a.flatten }
  # => ["0123456789"]

  sample("re2 [[:digit:]]") { RE2('([[:digit:]]+)').scan(haystack).to_a.flatten }
  # => ["0123456789"]

  sample("rust \\d") { RustRegexp.new('\d+').scan(haystack) }
  # => ["0123456789٠١٢٣٤٥٦٧٨٩߀߁߂߃߄߅߆߇߈߉"] -- ok

  sample("rust \\d non-unicode") { RustRegexp.new('\d+', unicode: false).scan(haystack) }
  # => ["0123456789"]
end

def b
  haystack = "- Yes, Fräulein."

  sample("ruby \\b") { haystack.scan(/\b[0-9A-Za-z_]+\b/) }
  # => ["Yes"] -- ok

  sample("re2 \\b") { RE2('(\b[0-9A-Za-z_]+\b)').scan(haystack).to_a.flatten }
  # => ["Yes", "Fr", "ulein"]

  sample("rust \\b") { RustRegexp.new('\b[0-9A-Za-z_]+\b').scan(haystack) }
  # => ["Yes"] -- ok

  sample("rust \\b non-unicode") { RustRegexp.new('\b[0-9A-Za-z_]+\b', unicode: false).scan(haystack) }
  # => ["Yes", "Fr", "ulein"]
end

def s
  haystack = " \u200A\u2000"

  sample("ruby \\s")             { haystack.scan(/\s/).size }                                 # 1
  sample("ruby [[:space:]]")     { haystack.scan(/[[:space:]]/).size }                        # 3 -- ok
  sample("re2 \\s")              { RE2('(\s)').scan(haystack).to_a.size }                     # 1
  sample("re2 [[:space:]]")      { RE2('([[:space:]])').scan(haystack).to_a.size }            # 1
  sample("rust \\s")             { RustRegexp.new('\s').scan(haystack).size }                 # 3 -- ok
  sample("rust \\s non-unicode") { RustRegexp.new('\s', unicode: false).scan(haystack).size } # 1
end

def bounded_repeat_max
  sample("ruby .{0,100000}") { Regexp.new('.{0,100000}') }
  # => ok

  sample("ruby .{0,100000}") { Regexp.new('.{0,100001}') }
  # => too big number for repeat range

  sample("re2 .{0,1000}") { RE2('.{0,1000}').ok? }
  # => true

  sample("re2 .{0,1001}") { RE2('.{0,1001}').ok? }
  # => false
  # => invalid repetition size: {0,1001}

  sample("rust .{0,10082}") { RustRegexp.new('.{0,10082}') }
  # => ok

  sample("rust .{0,10083}") { RustRegexp.new('.{0,10083}') }
  # => ArgumentError: Compiled regex exceeds size limit of 10485760 bytes.

  sample("rust .{0,87379} non-unicode") { RustRegexp.new('.{0,87379}', unicode: false) }
  # => ok

  sample("rust .{0,87380} non-unicode") { RustRegexp.new('.{0,87380}', unicode: false) }
  # => ArgumentError: Compiled regex exceeds size limit of 10485760 bytes.

  sample("rust \w{0,209}") { RustRegexp.new('\w{0,209}') }
  # => ok

  sample("rust \w{0,210}") { RustRegexp.new('\w{0,210}') }
  # => ArgumentError: Compiled regex exceeds size limit of 10485760 bytes.

  sample("rust \w{0,77099} non-unicode") { RustRegexp.new('\w{0,77099}', unicode: false) }
  # => ok

  sample("rust \w{0,77100} non-unicode") { RustRegexp.new('\w{0,77100}', unicode: false) }
  # => ArgumentError: Compiled regex exceeds size limit of 10485760 bytes.
end

def invalid_utf8
  haystack = "\xfc\xa1\xa1\xa1\xa1\xa1abc"

  sample("ruby invalid UTF-8") { haystack.scan(/.+/) }
  # => ArgumentError: invalid byte sequence in UTF-8 (ArgumentError)

  sample("re2 invalid UTF-8") { RE2('(.+)').scan(haystack).to_a.flatten }
  # => ["abc"]

  sample("rust invalid UTF-8") { RustRegexp.new('.+').scan(haystack) }
  # => ["abc"]
end

w
d
b
s
bounded_repeat_max
invalid_utf8

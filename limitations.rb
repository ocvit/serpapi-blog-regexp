require "re2"
require "rust_regexp"
require "pry"

# Ruby: \w, \d, \s are NOT unicode aware -- can be replaced with [[:alpha:]], [[:digit:]], [[:space:]], \b is OK
# RE2: \w, \d, \s, \b are NOT unicode aware, no replacement
# Rust: OK by default

def sample(name)
  result = yield

  puts "#{name.ljust(20)} | #{result.inspect}"
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
end

def b
  haystack = "- Yes, Fräulein."

  sample("ruby") { haystack.scan(/\b[0-9A-Za-z_]+\b/) }
  # => ["Yes"] -- ok

  sample("re2") { RE2('(\b[0-9A-Za-z_]+\b)').scan(haystack).to_a.flatten }
  # => ["Yes", "Fr", "ulein"]

  sample("rust") { RustRegexp.new('\b[0-9A-Za-z_]+\b').scan(haystack) }
  # => ["Yes"] -- ok
end

def s
  haystack = " \u200A\u2000"

  sample("ruby \\s") { haystack.scan(/\s/).size }                             # 1
  sample("ruby [[:space:]]") { haystack.scan(/[[:space:]]/).size }            # 3 -- ok
  sample("re2 \\s") { RE2('(\s)').scan(haystack).to_a.size }                  # 1
  sample("re2 [[:space:]]") { RE2('([[:space:]])').scan(haystack).to_a.size } # 1
  sample("rust \\s") { RustRegexp.new('\s').scan(haystack).size }             # 3 -- ok
end

w
d
b
s

# nltk >= 3.10.4 refuses data dirs another account can write to or owns. On the runner that
# includes llama-index's bundled nltk_cache, so SentenceSplitter's stopwords lookup fails.
# Copy the bundled data somewhere private and point NLTK_DATA (read by nltk and llama-index) at it.
# Source this file so the current step sees NLTK_DATA too; GITHUB_ENV carries it to later steps.
src=$(python -c "import llama_index.core, os; print(os.path.join(os.path.dirname(llama_index.core.__file__), '_static', 'nltk_cache'))")
export NLTK_DATA="$RUNNER_TEMP/nltk_data"
install -d -m 700 "$NLTK_DATA"
cp -r "$src/." "$NLTK_DATA/"
chmod -R go-w "$NLTK_DATA"
echo "NLTK_DATA=$NLTK_DATA" >> "$GITHUB_ENV"

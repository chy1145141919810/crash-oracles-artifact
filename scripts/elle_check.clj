;; Run Elle's rw-register checker (the library bundled in the elle-cli uberjar) over a list of
;; EDN histories with an explicit option map, and print one line per history:
;;   <file> TAB <valid?> TAB <anomaly types>
;;
;; elle-cli itself does not expose Elle's :wfr-keys? / :linearizable-keys? / :sequential-keys?
;; options, so this script is used for the configurations that need them. The default
;; configuration is run through the unmodified elle-cli command line instead.
;;
;; usage: java -cp elle-cli-0.1.11-standalone.jar clojure.main elle_check.clj '<opts edn>' <file-list>
(require '[elle.rw-register :as rw]
         '[jepsen.history :as h]
         '[clojure.edn :as edn]
         '[clojure.java.io :as io])
(import '(java.io PushbackReader))

(defn read-history [f]
  (with-open [r (PushbackReader. (io/reader f))]
    (->> (repeatedly #(edn/read {:eof nil} r))
         (take-while identity)
         vec)))

(let [[optstr listfile] *command-line-args*
      opts (edn/read-string optstr)]
  (doseq [f (remove empty? (line-seq (io/reader listfile)))]
    (let [a (try (rw/check opts (h/history (read-history f)))
                 (catch Throwable t {:valid? :error :anomaly-types [(.getName (class t))]}))
          v (:valid? a)]
      (println (str f "\t" (if (keyword? v) (name v) v) "\t" (pr-str (vec (:anomaly-types a))))))))
(shutdown-agents)
(System/exit 0)

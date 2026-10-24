;; Print Elle's anomalies for one history, to see why it was reported.
;; usage: java -cp elle-cli-0.1.11-standalone.jar clojure.main elle_explain.clj '<opts edn>' <file.edn>
(require '[elle.rw-register :as rw]
         '[jepsen.history :as h]
         '[clojure.edn :as edn]
         '[clojure.java.io :as io]
         '[clojure.pprint :refer [pprint]])
(import '(java.io PushbackReader))

(defn read-history [f]
  (with-open [r (PushbackReader. (io/reader f))]
    (->> (repeatedly #(edn/read {:eof nil} r)) (take-while identity) vec)))

(let [[optstr f] *command-line-args*
      a (rw/check (edn/read-string optstr) (h/history (read-history f)))]
  (println "valid?" (:valid? a) "types" (:anomaly-types a))
  (binding [*print-length* 12 *print-level* 7]
    (pprint (into {} (for [[k v] (:anomalies a)] [k (take 2 v)])))))
(shutdown-agents)
(System/exit 0)

(require '[elle.rw-register :as rw] '[elle.core :as elle] '[bifurcan-clj.graph :as g] '[bifurcan-clj.core :as b]
         '[jepsen.txn :as txn] '[jepsen.history :as h] '[clojure.edn :as edn] '[clojure.java.io :as io])
(import '(java.io PushbackReader))
(defn read-history [f]
  (with-open [r (PushbackReader. (io/reader f))]
    (->> (repeatedly #(edn/read {:eof nil} r)) (take-while identity) vec)))
(let [[f kstr] *command-line-args*
      k (Long/parseLong kstr)
      hist (h/history (read-history f))
      rt (:graph (elle/realtime-graph hist))
      ekg (rw/ext-key-graph rt)]
  (doseq [op (sort-by :index (g/vertices rt))]
    (when (some #(= k (second %)) (:value op))
      (let [m (.get ^io.lacuna.bifurcan.IMap ekg op nil)
            bs (when m (.get ^io.lacuna.bifurcan.IMap m k nil))]
        (println "op" (:index op) (:type op) "proc" (:process op)
                 "ext-reads" (get (txn/ext-reads (:value op)) k :none)
                 "ext-writes" (get (txn/ext-writes (:value op)) k :none)
                 "downstream-for-key" (when bs (sort (map :index bs))))))))
(shutdown-agents)
(System/exit 0)